# Maturitní projekt: Mobilní aplikace pro predikci výskytu hub
## 1. Úvod a motivace
Česká republika je známá svou silnou houbařskou tradicí. Úspěch při sběru hub však často závisí na náhodě nebo hlubokých znalostech místního prostředí. Tento projekt si klade za cíl digitalizovat a zefektivnit tento proces za pomoci moderních technologií. Výsledkem bude mobilní aplikace, která na základě analýzy enviromentálních dat (počasí a složení lesa) dokáže uživateli lokalizovat místa s nejvyšší pravděpodobností výskytu hub.
## 2. Cíl projektu
Hlavním cílem projektu je vývoj mobilní aplikace, která:
 * **Vypočítá pravděpodobnost** celkového růstu hub v dané lokalitě.
 * **Specifikuje druhy hub**, které mají v daném lese ideální podmínky (např. hřiby pod smrky/duby, křemenáče pod břízami).
 * **Zobrazí přehlednou mapu** s pravděpodobnosti výskytu a navigací.
## 3. Datové zdroje a integrace
Aplikace funguje jako integrační platforma pro tři hlavní pilíře dat:
### A. Český hydrometeorologický ústav (ČHMÚ)
 * **Využití:** Získávání dat o srážkách za poslední dny, teplotě vzduchu a vlhkosti půdy.
 * **Význam:** Vlhkost a teplota jsou klíčovými spouštěči růstu podhoubí.
### B. Lesnická mapa (ÚHÚL / otevřená data)
 * **Využití:** Analýza druhového složení lesních porostů (listnaté vs. jehličnaté lesy, konkrétní dřeviny) a stáří lesa.
 * **Význam:** Určení, *jaké* konkrétní druhy hub v dané oblasti rostou na základě jejich symbiózy (mykorhizy) se stromy.
### C. OpenStreetMap (OSM)
 * **Využití:** Mapový podklad pro uživatelské rozhraní, zobrazení lesních cest, hranic lesů a topografie terénu.
 * **Význam:** Zajištění orientace uživatele přímo v terénu a vizualizace výsledných dat.
## 4. Architektura a Algoritmus
Aplikace bude obsahovat predikční algoritmus, který kombinuje získaná data:
```
[Data ČHMÚ: Srážky + Teplota] 
             +                       => [Predikční Algoritmus] => [Heatmapa na OpenStreetMap]
[Lesnická mapa: Typy stromů]

```
 1. **Sběr dat:** Backend aplikace (nebo lokální procesor) si vyžádá data z API ČHMÚ a geografická data o lesích.
 2. **Vyhodnocení:** Algoritmus porovná aktuální meteorologické podmínky s biologickými nároky jednotlivých hub a mapou podloží.
 3. **Vizualizace:** Výstup je vykreslen jako barevná vrstva (heatmapa) na podkladu OpenStreetMap.
## 5. Klíčové funkce aplikace
 * **Mapa výskytu:** Interaktivní mapa s barevným označením šancí na úspěch (např. červená = sucho/nerostou, zelená = ideální podmínky).
 * **Houbařský atlas s filtrem:** Seznam hub propojený s mapou – uživatel si vybere "Hřib smrkový" a aplikace zvýrazní lesy, kde je aktuálně nejvyšší šance ho najít.
 * **Moje místa (Offline režim):** Možnost uložit si polohu zaparkovaného auta nebo oblíbeného "tajného" místa i bez internetového signálu v lese.
## 6. Přínos projektu
Projekt prokazuje schopnost pracovat s otevřenými datovými sadami (Open Data), propojovat heterogenní API (meteorologie + geografie) a prezentovat komplexní data v uživatelsky přívětivé mobilní formě. Má reálné využití a kombinuje programování s praktickou biologií a geografií.
