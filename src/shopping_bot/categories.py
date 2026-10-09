"""Offline category matching; unknown or conflicting names stay unclassified."""
import re
import unicodedata
import json
from pathlib import Path
from functools import lru_cache

CATEGORIES = {
    "produce": "🥬 Овочі та фрукти",
    "bakery": "🍞 Хліб і випічка",
    "dairy": "🥛 Молочне та яйця",
    "meat": "🥩 М’ясо та риба",
    "pantry": "🍚 Крупи та макарони",
    "spices": "🧂 Приправи, соуси й олія",
    "frozen": "🧊 Заморожене та напівфабрикати",
    "snacks": "🍫 Снеки та солодощі",
    "drinks": "🥤 Напої",
    "cleaning": "🧽 Побутова хімія",
    "care": "🧴 Догляд і здоров’я",
    "pets": "🐾 Для тварин",
    "home": "🏡 Дім і сад",
    "auto": "🚗 Для авто",
    "other": "📦 Інше",
}
# Whole words, including common Ukrainian inflections and Portuguese labels.
WORDS = {
    "vegetables": "картопля картоплю картоплі помідори помідор огірки огірок морква моркву цибуля цибулю часник капуста броколі кабачок кабачки batata batatas tomate tomates cebola cenoura pepino legumes",
    "fruit": "мандарини мандарин мандаринів яблука яблуко яблук банани банан апельсини апельсин лимон лимони груша груші виноград полуниця полуницю ківі maçã maçãs banana bananas tangerina tangerinas laranja laranjas limão uvas morangos fruta",
    "dairy": "молоко молока кефір йогурт йогурти сир сиру сметана вершки масло яйця яєць яйце leite queijo iogurte iogurtes manteiga ovos ovo natas",
    "meat": "курка курку курятина яловичина свинина фарш риба рибу лосось тунець ковбаса сосиски frango carne peixe salmão atum porco",
    "bakery": "хліб хліба булка булки батон круасан круасани pão pao croissant padaria",
    "pantry": "рис гречка макарони паста борошно цукор сіль олія консерви крупа arroz massa farinha açúcar sal azeite óleo",
    "drinks": "вода воду води кава каву кави чай сік соку пиво вино água agua café cafe chá cha sumo cerveja vinho",
    "frozen": "морозиво gelado gelados congelados",
    "cleaning": "кондиціонер кондиціонери кондиціонера кондиціонеру порошок відбілювач amaciador detergente lixívia lixivia",
    "care": "шампунь шампуню мило мила дезодорант прокладки підгузки shampoo champô sabonete desodorizante fraldas",
}

ENGLISH_WORDS = {
 'vegetables':'potato potatoes tomato tomatoes cucumber cucumbers carrot carrots onion onions garlic broccoli cabbage',
 'fruit':'apple apples banana bananas mandarin mandarins orange oranges lemon lemons grapes strawberry strawberries pear pears',
 'dairy':'milk eggs egg butter cream yogurt cheese sour cream',
 'meat':'chicken beef pork fish salmon tuna sausage', 'bakery':'bread croissant bakery',
 'pantry':'rice pasta flour sugar salt oil beans', 'drinks':'water coffee tea juice beer wine',
 'frozen':'frozen ice cream fries', 'cleaning':'detergent bleach laundry', 'care':'shampoo soap deodorant toothpaste',
}
for category,words in ENGLISH_WORDS.items():
    WORDS[category]+=' '+words

# Separate aisles and common spoken variants, including existing catalog names.
WORDS["produce"] = WORDS.pop("vegetables") + " " + WORDS.pop("fruit") + " авокадо авокади буряк буряки салат lettuce avocado avocados beet beetroot abacate beterraba"
WORDS["pantry"] = "рис гречка макарони паста борошно цукор крупа крупи квасоля фасоль сочевиця вівсянка arroz massa farinha açúcar feijão rice pasta flour sugar beans lentils oats cereal cereals"
WORDS["spices"] = "сіль перець приправа приправи спеції соус кетчуп майонез олія оливкова оцет sal azeite óleo molho vinagre salt pepper spice spices sauce ketchup mayonnaise oil vinegar"
WORDS["snacks"] = "снеки снекі снек снеків горішки горіхи чипси чіпси шоколад цукерки печиво вафлі nuts snack snacks chips crisps chocolate candy cookies biscuits bolachas doces frutos"
WORDS["frozen"] += " піца пельмені вареники заморожена заморожений заморожені напівфабрикати pizza dumplings congelado congelada congeladas"
WORDS["meat"] += " мясо індичка бекон шинка turkey bacon ham peru presunto"
WORDS["care"] += " зубна зубну зубний щітка ліки вітаміни пластир toothpaste toothbrush medicine vitamins penso medicamentos"
WORDS["pets"] = "корм наповнювач повідець нашийник cat dog pet kibble litter ração racao areia coleira"
WORDS["home"] = "лампочка батарейки горщик ґрунт добриво губки lamp bulb batteries pot soil fertilizer pilhas lâmpada vaso terra adubo"
WORDS["auto"] = "омивач автошампунь антифриз двірники склоомивач washer antifreeze coolant wipers lava vidros anticongelante"

def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold().translate(str.maketrans({"’":"", "ʼ":"", "'":"", "`":""}))

@lru_cache(maxsize=1)
def food_dictionary():
    path = Path(__file__).with_name("food_dictionary.json")
    return json.loads(path.read_text())["entries"] if path.exists() else {}

def infer_category(name):
    text = normalize(name)
    # Specific contexts take priority over generic words such as oil, milk or pasta.
    priority = [
        ("auto", r"\b(?:для авто|для машини|моторн\w* (?:олив\w*|масл\w*)|engine oil|motor oil|car shampoo|омивач|склоомивач|антифриз|двірники|washer fluid|coolant|wipers)\b"),
        ("pets", r"\b(?:корм|наповнювач|для кот\w*|для собак\w*|для тварин|cat food|dog food|pet food|cat litter|ração|racao)\b"),
        ("care", r"\b(?:зубн\w* паст\w*|toothpaste|toothbrush|кондиціонер\w* для волосся|hair conditioner)\b"),
        ("frozen", r"\b(?:ice cream|french fries|картопл\w* фрі|фрі|заморожен\w*|frozen|морозиво|gelado\w*|піца|pizza|пельмені|вареники)\b"),
        ("drinks", r"\b(?:кава|каву|кави|coffee|café|чай|tea)\b"),
    ]
    for category, pattern in priority:
        if re.search(pattern, text):
            return category
    if re.search(r"\b(волосся|волос|cabelo|cabelos)\b", text) and re.search(r"\b(кондиціонер\w*|amaciador|condicionador)\b", text):
        return "care"
    known = food_dictionary().get(text)
    if known in CATEGORIES:
        return known
    tokens = set(re.findall(r"[^\W\d_]+", text))
    matches = {category for category, words in WORDS.items() if tokens & set(words.split())}
    return next(iter(matches)) if len(matches) == 1 else "other"
