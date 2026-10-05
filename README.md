# Maturitní projekt: Webová aplikace pro predikci výskytu hub

## 1. Úvod a motivace

Česká republika je známá svou silnou houbařskou tradicí. Úspěch při sběru hub však často závisí na náhodě nebo hlubokých znalostech místního prostředí. Tento projekt si klade za cíl digitalizovat a zefektivnit tento proces za pomoci moderních webových technologií. Výsledkem bude webová aplikace přístupná z jakéhokoliv zařízení (PC, tablet, mobilní telefon), která na základě analýzy enviromentálních dat (počasí a stáří lesa) dokáže uživateli lokalizovat místa s nejvyšší pravděpodobností výskytu hub.

## 2. Cíl projektu

Hlavním cílem projektu je vývoj webové aplikace, která:

* **Vypočítá pravděpodobnost** celkového růstu hub v dané lokalitě.
* **Zohlední stáří lesního porostu** jako klíčového faktoru pro rozvoj podhoubí a akumulaci vlhkosti.
* **Zobrazí přehlednou interaktivní mapu** s pravděpodobností výskytu hub a možností vyhledávání vhodných oblastí.

## 3. Datové zdroje a integrace

Aplikace funguje jako integrační platforma pro tři hlavní pilíře dat:

### A. Český hydrometeorologický ústav (ČHMÚ)

* **Využití:** Získávání dat o srážkách za poslední dny, teplotě vzduchu a vlhkosti půdy.
* **Význam:** Vlhkost a teplota jsou klíčovými spouštěči růstu podhoubí.

### B. Lesnická mapa (ÚHÚL / otevřená data)

* **Využití:** Analýza stáří lesních porostů (např. mladiny vs. staré, zralé lesy).
* **Význam:** Stáří lesa má zásadní vliv na mikroklima, hromadění humusu a stabilizaci podhoubí – starší porosty zpravidla poskytují stabilnější podmínky pro růst hub než mladé výsadby.

### C. OpenStreetMap (OSM)

* **Využití:** Mapový podklad pro webové uživatelské rozhraní, zobrazení lesních cest, hranic lesů a topografie terénu.
* **Význam:** Zajištění orientace uživatele v terénu a vizualizace výsledných dat na webu.

## 4. Architektura a Algoritmus

Aplikace obsahuje predikční algoritmus běžící na backendu, který kombinuje získaná data:

```
[Data ČHMÚ: Srážky + Teplota] 
             +                       => [Predikční Algoritmus] => [Heatmapa na OpenStreetMap]
[Lesnická mapa: Stáří lesa]

```

1. **Sběr dat:** Backend webové aplikace si vyžádá data z API ČHMÚ a geografická data o stáří lesů.
2. **Vyhodnocení:** Algoritmus porovná aktuální meteorologické podmínky se stářím lesního porostu a vypočítá index vhodnosti pro růst hub.
3. **Vizualizace:** Výstup je vykreslen jako barevná vrstva (heatmapa) přímo ve webovém prohlížeči na podkladu OpenStreetMap.

## 5. Klíčové funkce aplikace

* **Interaktivní mapa výskytu:** Webová mapa s barevným označením šancí na úspěch (např. červená = sucho/nevhodné porosty, zelená = ideální meteorologické podmínky a vzrostlý les).
* **Filtr stáří lesa:** Možnost filtrovat zobrazené oblasti podle věkových tříd lesního porostu (např. porosty nad 40 let).
* **Uživatelská místa a export (Moje místa):** Možnost uložení oblíbených souřadnic do profilu/lokálního úložiště prohlížeče (LocalStorage) nebo export vybraných tras/bodů ve formátu GPX/KML.
* **Responzivní design:** Optimalizované webové rozhraní dostupné jak na stolním počítači při plánování výletu, tak na displeji smartphonu přímo v terénu.

## 6. Přínos projektu

Projekt prokazuje schopnost pracovat s otevřenými datovými sadami (Open Data), propojovat heterogenní API (meteorologie + geografie) a prezentovat komplexní data v uživatelsky přívětivé webové formě. Má reálné využití a kombinuje vývoj webových aplikací s praktickou biologií a geografií.
