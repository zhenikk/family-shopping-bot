"""Offline category matching; unknown or conflicting names stay unclassified."""
import re
import unicodedata

CATEGORIES = {
    "vegetables": "🥕 Овочі",
    "fruit": "🍊 Фрукти",
    "dairy": "🥛 Молочне та яйця",
    "meat": "🥩 М’ясо та риба",
    "bakery": "🍞 Хліб та випічка",
    "pantry": "🥫 Бакалія",
    "drinks": "🥤 Напої",
    "frozen": "🧊 Заморожене",
    "cleaning": "🧽 Побутова хімія",
    "care": "🧴 Особиста гігієна",
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

def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()

def infer_category(name):
    text = normalize(name)
    # Conditioner for hair belongs in personal care; laundry conditioner in cleaning.
    if re.search(r"\b(волосся|волос|cabelo|cabelos)\b", text):
        if re.search(r"\b(кондиціонер\w*|amaciador|condicionador)\b", text):
            return "care"
    tokens = set(re.findall(r"[^\W\d_]+", text))
    matches = {category for category, words in WORDS.items() if tokens & set(words.split())}
    return next(iter(matches)) if len(matches) == 1 else "other"
