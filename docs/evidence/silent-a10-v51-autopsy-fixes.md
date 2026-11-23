# Silent A10 v5.1 · parad ablation av gratisdraft, bosstaktik och makro

## Hypoteser och beslut före körningen

Referensen är Linux-körningen av `all_v2_search_v5` vid `efd98778688eac038cc946693cadd4389cb30d4d`. V5.1 har tre oberoende booleska inställningar i policymanifestet, alla av som standard. Den femte armen aktiverar alla tre, oberoende av hur de enskilda armarna utfaller. Det gör det möjligt att se om kombinationen håller. Fem armar räcker inte för att skatta alla parvisa interaktioner. [Låst protokoll och alla 256 lobbys](silent-a10-v51-dev-panel.json)

### Varför gratisdraft och shop värderade Accelerant olika

`deck_model.json` i championpaketet begränsar `DeckPolicy` till shop och eld. En gratis kortbelöning går till `StrategyModel`. V5 använder `unified_draft=true`, tröskeln 7,407681, storleksstraff 0 och skalning av de historiska kortoffseten 0. `RunPolicy.card_value` har `deck_effects=false`. Accelerant har `stats.accelerant=1`, men saknar egen PoisonPower och PoisonPerTurn. Därför blir både gifttermen och interaktionen med antalet giftkällor noll. Kortet får bara den generella powerbonusen 5 × 0,738025 = 3,6901 i råvärde vid kostnad 1. För första exemplaret blir grundpoängen 0,35 × (3,6901 − 7,4077) = −1,3011. Modellens lilla kortvikt och övriga egenskaper räcker aldrig upp till skip på 0. Den saknade multiplikatoreffekten förklarar också varför fler giftkällor inte höjer detta korts gratispoäng.

En ompoängsättning av de **132 sparade erbjudandena** gav Accelerant mellan **−1,789 och −0,731**. På `V5DIAG_0028`, Act 1 våning 12, blev totalen −0,8220 medan samma kort och lek fick +4,125 i butikens graderare. Där läser `DeckPolicy.terms` rätt variabel och räknar `accelerant × min(29, 1.45 × poison + 5 × noxious)`, med akt- och energikostnadsjustering. `merchant_choice` jämför sedan kortets köpnytta `1.4 + max(-6, grade)` med andra köp och värdet av kvarvarande guld. 47 köp och 0 gratisval är följden av två olika värderingar av samma effekt. [V5-autopsin och observationsunderlaget](silent-a10-v5-lategame-autopsy.md)

| Kort | Fria val / erbjudanden i v5 | Shopköp | Mekanik och avgränsning |
|---|---:|---:|---|
| Accelerant | 0/132 | 47 | Extra gifttick. Första exemplaret får butikens skalning när leken kan börja lägga gift. Bubble Bubble ensam kan bara förstärka befintligt gift. |
| Accuracy | 0/110 | 10 | Extra skada per Shiv. Första exemplaret får skalningen med en tryckt Shiv-generator. |
| Phantom Blades | 0/113 | 11 | Extra skada på första Shiv varje tur. Samma villkor. |
| Infinite Blades | 0/118 | 17 | Skapar själv en Shiv varje tur. Första exemplaret får butikens återkommande värde. |
| Afterimage / Well-Laid Plans / Tools of the Trade | 0/36, 0/51, 0/34 | 0, 0, 0 | Utlöst block, behållen hand respektive drag/discard per tur saknas i grundvärdet. Ingen motsvarande serie shopköp i denna panel. |
| Noxious Fumes / Footwork | 59/114, 46/119 | 57, 1 | PoisonPerTurn respektive DexterityPower finns redan i grundvärdet. |
| Calculated Gamble / Speedster | 0/106, 0/107 | 1, 0 | Ett helt handbyte respektive skada vid drag fångas dåligt. Köpunderlaget är tunt. |

Draftflaggan återanvänder butikens befintliga, akt- och kostnadsjusterade skalningsterm för de fyra första korten som tillägg till grundvärdet. Det värdet går genom både grundpoängen och modellens `take:value`. Effekten på totalpoängen per extra råpoäng är 0,35 + 0,55 × (−1,54747)/10 ≈ 0,26489. Det här är en gemensam komponentprövning av fyra kort.

### Bosstaktik när v2-sökning faller tillbaka

- **The Insatiable.** V5:s `cheap`-plan reserverade energi vid högst tre Sandpit för en Escape som kostar ett, men först vid ett för en dyrare Escape. V5.1 flyttar dessa gränser till fyra respektive två. Vid två räcker en extrapolerad skadehastighet inte för att släppa reservationen. Säkra dödande träffar, dödligt befintligt gift och omedelbart överlevnadsbehov har fortsatt prioritet.
- **Knowledge Demon.** Sloth begränsar spelaren till tre kort per runda. Det publika fältet `amount` är taket. Policyn räknar utförda spelarkommandon under Sloth och nollställer per runda. Den jämför kortens nytta med energi per återstående plats, tar bort gratisbonus och begränsar nyttan av skapade Shivs och drag som behöver följdspel. Överlevnadsplaner får som mest använda det återstående antalet manuella kort och kan använda drycker separat. Motorns `can_play` avgör vad som faktiskt går att spela. Automatiska spel kan göra den observerade återstående budgeten till en övre gräns.
- **Queen.** I den faktiska stridsobservationen har Torch Head Amalgam Minion och lämnar striden när ledaren dör. Legacy sänker minions skadevärde och räknar med att ett ledardödande spel också undanröjer minionens attack. I sex dödsstrider levde båda vid döden, och v5 angrep båda målen (33/12). Det stöder att direkt skada på Queen kan vara rätt. Materialet visar inget generellt målprioritetsfel och ingen Queen-regel ingår.

V2 får det frysta legacyförslaget i sin sökning. Bosstaktiken får påverka utförd handling först vid fallback eller när legacy själv styr. [Frysta beslut och dödsstrider](silent-a10-v5-lategame-autopsy.md)

### Makro

- **This or That?** Plain kostar 6 HP och ger 41–68 guld i v5:s 75 observerade erbjudanden. Ornate ger en slumpmässig relik och Clumsy. V5 upptäcker redan både relik och förbannelse genom beskrivningen. Den fasta förbannelsevikten saknar senare removalutgifter. I autopsin betalade policyn 3 200 guld efter de 75 valen, i snitt 42,67 guld per Ornate. V5.1 räknar denna observerade utgift i eventmodellens enheter (75 guld per poäng) när Plain lämnar minst v5:s normala vilogräns, 77 % HP, och spelaren kan ta emot guld. Båda poängen får sedan konkurrera som vanligt. Utgiften är observerad. Det alternativa nettovärdet av att avstå från reliken kräver en jämförelse av runutfall.
- **Ancient.** Ruttens Bellman-jämförelse tillät ett direkt hopp till rad ett när rad noll också var laglig. De två dokumenterade fallen gick miste om ett helt relikval. Makroflaggan väljer den lagliga Ancient-rutan på rad noll vid ingången till Act 2 eller 3.
- **Eld.** V5 valde mellan vila och smide vid 77 % HP i championpaketet. I den historiska gruppen vid sista Act 2-elden var det framför allt redan skadade lekar som vilade (10/84 clears), medan friskare lekar smidde (7/20). Detta ger ingen skattning av vinsten av att flytta tröskeln. Den riktade ändringen använder redan provad Kindle-logik när v5 vill smida och Pumpkin Candle har noll laddningar i Act 2–3. Policyvalet mellan Philosopher's Stone och Velvet Choker ingår inte i flaggan.
