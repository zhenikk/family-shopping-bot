import json, os, sys, tempfile, threading
from pathlib import Path
project = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(project / 'src'), str(project / 'tests')]
from shopping_bot.store import Store
from shopping_bot.app import ShoppingBot
from shopping_bot.webserver import make_server
from test_bot import FakeTelegram
from test_webserver import signed_data, TOKEN
from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    store=Store(root/'test.sqlite3');store.join(1,'Анна');store.join(2,'Іван')
    for name,note in [('Молоко','Улюблена упаковка, 1 л'),('Яйця',''),('Картопля','Купити в Mercadona'),('Мандарини',''),('Кондиціонер для білизни','Такий самий, як минулого разу')]:
        product=store.ensure_product(name,note or None);store.add_need(product,1)
    store.ensure_product('Кава','Без кофеїну')
    bot=ShoppingBot(FakeTelegram(),store,'private-family-code',root/'photos',root/'whisper',root/'model')
    server=make_server(bot,TOKEN,port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            options = {'headless': True}
            if os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
            browser=p.chromium.launch(**options)
            page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=2)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('https://telegram.org/js/telegram-web-app.js',lambda route:route.fulfill(body=''))
            page.add_init_script('window.Telegram={WebApp:{initData:'+json.dumps(signed_data())+',ready(){},expand(){},onEvent(){},colorScheme:"light",BackButton:{onClick(){},show(){},hide(){}},HapticFeedback:{notificationOccurred(){}}}};')
            page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_load_state('networkidle')
            page.evaluate('document.fonts.ready')
            faces=page.evaluate('Array.from(document.fonts).map(f=>({family:f.family,status:f.status}))')
            assert {f['family'] for f in faces if f['status']=='loaded'} >= {'Onest','Manrope'},faces
            page.get_by_role('button',name='Відкрити Картопля',exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path='/tmp/shopping-miniapp-mobile.png',full_page=False)
            page.get_by_role('button',name='Відкрити Картопля',exact=True).click()
            page.get_by_label('Нотатка',exact=True).fill('Велика упаковка з Mercadona')
            page.get_by_role('button',name='Зберегти',exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            assert store.product_by_name('Картопля')['note']=='Велика упаковка з Mercadona'
            # Hold the actual purchase request: the check must react before the server.
            blocked = []
            page.route('**/api/buy', lambda route: blocked.append(route))
            page.get_by_role('button',name='Куплено: Картопля',exact=True).click()
            check = page.locator('.is-buying .product-check')
            check.wait_for()
            assert check.get_attribute('aria-pressed') == 'true'
            page.screenshot(path='/tmp/shopping-miniapp-check.png',full_page=False)
            page.get_by_role('button',name='Відкрити Картопля',exact=True).wait_for(state='hidden')
            assert blocked
            blocked[0].fulfill(status=503,content_type='application/json',body='{"error":"Тестова помилка мережі"}')
            page.get_by_role('button',name='Відкрити Картопля',exact=True).wait_for()
            assert any(row['id'] == store.product_by_name('Картопля')['id'] for row in store.needs())
            page.unroute('**/api/buy')
            page.get_by_role('button',name='Куплено: Картопля',exact=True).click()
            page.get_by_role('button',name='Відкрити Картопля',exact=True).wait_for(state='hidden')
            page.get_by_role('button',name='Скасувати',exact=True).click()
            page.get_by_role('button',name='Відкрити Картопля',exact=True).wait_for()
            page.get_by_role('button',name='Каталог',exact=True).click()
            page.get_by_role('button',name='Додати до списку: Кава',exact=True).click()
            page.get_by_role('button',name='Додати до списку: Кава',exact=True).wait_for(state='hidden')
            page.get_by_role('button',name='Додати товари',exact=True).click()
            page.get_by_label('Товари',exact=True).fill('Хліб, яблука')
            page.get_by_role('button',name='Перевірити список',exact=True).click()
            page.get_by_role('button',name='Додати все · 2',exact=True).click()
            page.get_by_role('button',name='Відкрити яблука',exact=True).wait_for()
            page.get_by_role('button',name='Історія',exact=True).click()
            assert page.locator('.history-row').count()>0
            assert not page.locator('.tools').is_visible()
            page.get_by_role('button',name='Покупки',exact=True).click()
            page.set_viewport_size({'width':320,'height':700})
            page.evaluate('document.body.classList.add("dark")')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.wait_for_timeout(250)
            page.evaluate('document.getElementById("toast").hidden=true')
            page.screenshot(path='/tmp/shopping-miniapp-dark.png',full_page=False,animations='disabled')
            assert not errors,errors
            print('PASS: immediate animated check before server response, failed request restores item; add/confirm, notes, buy/undo, readd, history, 320px layout, dark theme; no JS errors')
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join();bot.voice_pool.shutdown()
