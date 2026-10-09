# Shopping language QA

Run the automated suite:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

`tests/test_shopping_language_qa.py` contains 29 natural-language cases plus length and separator boundaries. It tests the actual offline parser. `tests/test_bot.py` tests draft → confirmation → shared database, ownership, repeated confirmation, keeping one duplicate while adding another product, and changed notes. `tests/test_extraction.py` tests API response validation and dietary variants before deduplication using mocked responses.

These are regression checks, not measured Whisper/DeepSeek accuracy. Live model outputs are not deterministic. Do not infer speech accuracy from mocked API tests.

## Manual voice acceptance

Use a separate test list/account. Send each utterance naturally, inspect the draft BEFORE confirming, then inspect the final list. Repeat with a second speaker and mild background noise. Never use another family's list for these tests.

| Utterance | Expected |
|---|---|
| Купи дві пачки масла, творог, кефір, три молока і одне молоко без лактози | Five products; regular milk 3, lactose-free milk 1; dairy category |
| Дві буханки хліба | Хліб; 2 буханки |
| Півтора літра молока | Молоко; 1.5 л (AI interpretation; offline fractional words not guaranteed) |
| Купи молоко, ні, краще кефір | Кефір only |
| Не купуй молоко, купи хліб | Хліб only |
| Я вже купив яйця, треба масло | Масло only (AI semantic interpretation) |
| Женя, як підеш у Меркадону, купи буряк. Дякую | Буряк; store may be a note, greetings never products |
| Buy two bottles of milk and one loaf of bread | Milk 2 bottles; bread 1 loaf |
| Купи звичайне молоко і молоко без лактози | Two separate variants |
| Масло без лактози і масло без солі | Separate variants; verify live extractor keeps salt modifier in name |
| Нічого купувати не треба | No shopping draft with invented products |
| Хліб, хліб | One product, no silent quantity increase |

## Lifecycle checks

1. Existing butter: `1 пачка; без лактози`. Dictate 2 packs: see current/proposed notes; nothing changes before confirmation.
2. Choose Keep unchanged for butter, confirm bread in same draft: butter unchanged, bread added.
3. Change the note from the second participant before confirmation: first confirmation asks for review, second applies reviewed proposal.
4. Press Confirm twice: no duplicate, no second write.
5. Cancel or open a replacement draft: old confirmation cannot mutate the list.
6. Both participants see the same final products; unrelated families see none.
7. Rename and edit a note containing `<`, `>`, `&`: display literal characters; no formatting error.
8. Groq/extraction timeout: fallback must remain usable; review all items before confirming.

Record release, input language, expected versus actual products/notes, provider, latency and whether fallback was used. A product disappearing, invented purchase, cross-family disclosure or mutation without confirmation blocks release. General negations/corrections in free-form speech and novel product modifiers require live evaluation; the offline fallback handles bounded explicit patterns only.
