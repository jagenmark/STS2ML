# Silent A10 v5.1 · parad ablation av gratisdraft, bosstaktik och makro

**Ta med `v51_boss_tactics` som kandidat till nästa parade v6-körning.** Två seeded-lobbys överlevde The Insatiable och gick fem respektive sju våningar längre. Ingen lobby fick en lägre slutvåning i den armen. För `v51_draft_fixes` motiverar de tre extra Act 2-clears en smalare prövning av Accelerant. Osäkerheten är stor och draftflaggan ändrar också värderingen av tre andra powers. Låt `v51_macro_fixes` och kombinationen förbli avstängda i v6. Ingen av de fem armarna vann en full run. [Maskinläsbar rapport](silent-a10-v51-autopsy-fixes.json)

## Fem armar på samma 256 seeds

Alla 1 280 native-starter avslutades utan omkörning eller avbruten lobby. Varje arm hade 128 default och 128 seeded. W/L/T är antalet högre, lägre och lika slutvåningar mot fryst v5 på samma seed. Act 1 clear, Act 2-bossentré, Act 2 clear, Act 3-bossentré och full vinst är antal av 256. För respektive Act 2-boss visas clears per faktiskt inträde. [Kvitton för alla starter](silent-a10-v51-receipts.jsonl.gz)

| Arm | Medelvåning | Δ våning [95 % KI] | W/L/T | A1 clear | A2 entré | A2 clear | Kaiser | Demon | Insatiable | A3 entré | Vinst |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fryst v5 | 23,0156 | +0,0000 [0,0000 … 0,0000] | 0/0/256 | 146 | 59 | 6 | 1/18 | 3/18 | 2/23 | 2 | 0 |
| Draft | 23,2227 | +0,2070 [−0,3398 … 0,7773] | 28/25/203 | 151 | 56 | 9 | 2/17 | 4/19 | 3/20 | 3 | 0 |
| Bosstaktik | 23,0625 | +0,0469 [0,0000 … 0,1211] | 2/0/254 | 146 | 59 | 8 | 1/18 | 3/18 | 4/23 | 2 | 0 |
| Makro | 23,0078 | −0,0078 [−0,0820 … 0,0586] | 1/1/254 | 146 | 60 | 5 | 0/18 | 3/19 | 2/23 | 2 | 0 |
| Kombinerad | 23,2148 | +0,1992 [−0,3360 … 0,7539] | 29/26/201 | 150 | 57 | 10 | 1/17 | 4/20 | 5/20 | 3 | 0 |

- **Bosstaktik.** `V51DEV_0021` gick från våning 33 till 38 och `V51DEV_0179` från 33 till 40. Båda slog The Insatiable. Alla 59 bossinträden, bossidentiteter och ingångs-HP matchade v5 på samma seed. Sju Insatiable-strider och nio Demon-strider fick olika beslutshash. För Demon blev det fortfarande 3/18 clears, andelen baskort under Sloth steg från 34/128 till 37/126 och båda armarna spelade fem powers under Sloth. Stödet för flaggan kommer från Escape. Två ändrade slutvåningar är ett litet underlag och KI:s nedre gräns är noll. Pröva flaggan igen tillsammans med v6:s nya söktäckning.
- **Draft.** Armen fick fem nya Act 2-clears och förlorade två gamla. Antalet bossentréer föll från 59 till 56. Draften tog Accelerant vid 34/71 belöningar och köpte det fortfarande vid 25/53 köptillfällen. Accuracy valdes 14/62, Phantom Blades 25/69 och Infinite Blades 55/81. Fryst v5 tog noll av respektive 61, 74 och 82 erbjudanden om de tre syskonkorten. Våningsskillnaden var positiv i båda aktlistelägena men KI omfattar både vinst och förlust. Bevara draftflaggan för experiment och pröva första Accelerant separat före aktivering i v6.
- **Makro.** Åtta av tio lobbys med olika beslutshash bytte först Ornate till Plain. I den gruppen gick en lobby fem våningar längre, en tappade sju och sin Kaiser-clear, och sex slutade på samma våning. De andra två ändrade först Smith till Kindle vid sista Act 2-elden och båda slutade på samma våning som v5. Alla tio första val verifierades i identiska publika tillstånd mot en hel återspelning av referensens beslutshash. Betalda Clumsy-removals minskade med fem och deras kostnad med 500 guld. Det fanns inget missat Ancient i den nya referensarmen. Panelen visar en verklig guldutgift för Ornate men ger inget stöd för att Plain ökar avancemanget.
- **Kombination.** Alla tre flaggor tillsammans gav sex nya och två förlorade Act 2-clears, tre Act 3-bossentréer och noll vinster. Den genomsnittliga våningsvinsten var +0,1992 med ett KI som omfattar noll. Kombinationen hade fyra fler Act 2-clears än v5 och endast en fler än enbart draft. Fem armar ger inget isolerat mått på hur exempelvis draft och Escape samverkar utan makroflaggan.

### Gratisval, butik och beslut i bossrummen

Gratis och shop visar val per erbjudande respektive köp per besök med ett köpbart exemplar. Sandpit-kolumnen med dödsfall visar fatala turavslut på ett delat med alla förluster mot The Insatiable. Sloth redovisas dels över alla Demon-strider, dels över de förlorade striderna. Olika lekar och stridslängder ändrar antal exponeringar.

| Arm | Accelerant gratis | Accelerant shop | Escape spelade | Sandpit=1 turavslut | Fatalt vid 1 / döda | Sloth basic / spel | Därav i dödsstrider | Sloth powers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fryst v5 | 0/69 | 25/53 | 31 | 15 | 14/21 | 34/128 | 24/91 | 5 |
| Draft | 34/71 | 25/53 | 27 | 13 | 11/17 | 27/150 | 17/107 | 4 |
| Bosstaktik | 0/69 | 25/53 | 43 | 12 | 10/19 | 37/126 | 28/91 | 5 |
| Makro | 0/69 | 26/55 | 31 | 15 | 14/21 | 36/133 | 26/96 | 5 |
| Kombinerad | 34/72 | 26/55 | 39 | 9 | 7/15 | 37/170 | 24/118 | 5 |

Alla 16 avvikande bosspar återspelades till identisk referenshash. Vid det första ändrade beslutet hade sökningen fallit tillbaka i samtliga 16. Mot The Insatiable valde den nya armen Frantic Escape fem gånger vid Sandpit fyra och två gånger vid Sandpit två. På båda nya clear-seeds ersatte Escape en Strike vid fyra. Av de nio första skillnaderna under Sloth var fyra byten från Blade Dance, bland annat två till vanlig Strike. Leading Strike byttes också till vanlig Strike en gång. En vanlig Strike byttes till en vanlig Defend. Bara en av de nio händerna hade en spelbar power, Fan of Knives. Där valde v5 Ultimate Strike och den nya armen Predator. Begränsningen av följdspel ändrade alltså Shivs värde utan att åstadkomma den förväntade minskningen av baskort. [Enskilda beslut, lagliga powers och orsak till fallback](silent-a10-v51-autopsy-fixes.json)

### Event, Ancient och eld

Alla armar kunde välja ett Ancient vid varje redovisat tillfälle och gjorde det. Referensen nådde 46 Ornate-erbjudanden och 31 eldar med laglig Kindle. De två Kindle-valen i makroarmen ersatte smide och den parade vinsten i slutvåning var noll för bägge. Ingångs-HP är medel bland dem som nådde Act 2-bossen.

| Arm | Ornate / Plain | Clumsy-removals / guld | Ancient besök / tillfällen | Kindle / tillfällen | Sista A2-elden vila/smid/Kindle | HP vid A2-boss |
|---|---:|---:|---:|---:|---:|---:|
| Fryst v5 | 46/0 | 30/3000 | 152/152 | 0/31 | 43/16/0 | 57,7 |
| Draft | 44/0 | 28/2800 | 160/160 | 0/24 | 44/12/0 | 59,4 |
| Bosstaktik | 46/0 | 30/3000 | 154/154 | 0/31 | 43/16/0 | 57,7 |
| Makro | 38/8 | 25/2500 | 151/151 | 2/31 | 44/14/2 | 57,5 |
| Kombinerad | 36/8 | 24/2400 | 160/160 | 1/24 | 45/11/1 | 59,3 |

### Parade vinster och förluster per milstolpe

Täljaren är antal seeds som nådde milstolpen enbart med den angivna armen. Nämnaren är antal som nådde den enbart med v5. JSON redovisar även gemensamma inträden och jämför clears bland de par som mötte samma boss. För enbart draft, bland par som båda nådde Knowledge Demon, vann armen noll nya clears och förlorade en. Dess två övriga nya Demon-clears kom från lobbys som v5 aldrig fick dit.

| Arm | A1 clear | A2 entré | A2 clear | A3 entré | Full vinst | Kaiser clear | Demon clear | Insatiable clear |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fryst v5 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| Draft | 13/8 | 8/11 | 5/2 | 1/0 | 0/0 | 1/0 | 2/1 | 2/1 |
| Bosstaktik | 0/0 | 0/0 | 2/0 | 0/0 | 0/0 | 0/0 | 0/0 | 2/0 |
| Makro | 0/0 | 1/0 | 0/1 | 0/0 | 0/0 | 0/1 | 0/0 | 0/0 |
| Kombinerad | 12/8 | 9/11 | 6/2 | 1/0 | 0/0 | 1/1 | 2/1 | 3/0 |

**Uppdelning per aktlisteläge.** Det finns 128 par per läge. Samma parade våningsmått används för vart och ett.

| Arm | Default Δ [95 % KI] | A2 clear | Vinst | Seeded Δ [95 % KI] | A2 clear | Vinst |
|---|---:|---:|---:|---:|---:|---:|
| Fryst v5 | +0,0000 [0,0000 … 0,0000] | 3 | 0 | +0,0000 [0,0000 … 0,0000] | 3 | 0 |
| Draft | +0,3281 [−0,4688 … 1,1562] | 6 | 0 | +0,0859 [−0,6953 … 0,8750] | 3 | 0 |
| Bosstaktik | +0,0000 [0,0000 … 0,0000] | 3 | 0 | +0,0938 [0,0000 … 0,2422] | 5 | 0 |
| Makro | −0,0156 [−0,1641 … 0,1172] | 2 | 0 | +0,0000 [0,0000 … 0,0000] | 3 | 0 |
| Kombinerad | +0,3672 [−0,4219 … 1,1797] | 6 | 0 | +0,0312 [−0,7344 … 0,7891] | 4 | 0 |

## Rotorsaker och förregistrerade ingrepp

Referensen är Linux-körningen av `all_v2_search_v5` vid `efd98778688eac038cc946693cadd4389cb30d4d`. V5.1 har tre oberoende booleska inställningar i policymanifestet, alla av som standard. Den femte armen aktiverar alla tre, oberoende av hur de enskilda armarna utfaller. Det gör det möjligt att se om kombinationen håller. Fem armar räcker inte för att skatta alla parvisa interaktioner. [Låst protokoll och alla 256 lobbys](silent-a10-v51-dev-panel.json)

### Varför gratisdraft och shop värderade Accelerant olika

`deck_model.json` i championpaketet begränsar `DeckPolicy` till shop och eld. En gratis kortbelöning går till `StrategyModel`. V5 använder `unified_draft=true`, tröskeln 7,407681, storleksstraff 0 och skalning av de historiska kortoffseten 0. `RunPolicy.card_value` har `deck_effects=false`. Accelerant har `stats.accelerant=1`, men saknar egen PoisonPower och PoisonPerTurn. Därför blir både gifttermen och interaktionen med antalet giftkällor noll. Kortet får bara den generella powerbonusen 5 × 0,738025 = 3,6901 i råvärde vid kostnad 1. För första exemplaret blir grundpoängen 0,35 × (3,6901 − 7,4077) = −1,3011. Modellens lilla kortvikt och övriga egenskaper räcker aldrig upp till skip på 0. I 95 av de 132 erbjudandena hade leken redan en giftkälla. Fler giftkällor höjer därmed aldrig den saknade interaktionstermen. I den gamla panelen klarade 8/24 lekar med Accelerant Act 2-bossen mot 9/80 utan. Historiken innehåller selektion via bland annat shop, korterbjudanden och tidigare överlevnad.

En ompoängsättning av de **132 sparade erbjudandena** gav Accelerant mellan **−1,789 och −0,731**. På `V5DIAG_0028`, Act 1 våning 12, blev totalen −0,8220 medan samma kort och lek fick +4,125 i butikens graderare. Där läser `DeckPolicy.terms` rätt variabel och räknar `accelerant × min(29, 1.45 × poison + 5 × noxious)`, med akt- och energikostnadsjustering. `merchant_choice` jämför sedan kortets köpnytta `1.4 + max(-6, grade)` med andra köp och värdet av kvarvarande guld. 47 köp och 0 gratisval är följden av två olika värderingar av samma effekt. [V5-autopsin och observationsunderlaget](silent-a10-v5-lategame-autopsy.md)

| Kort | Fria val / erbjudanden i v5 | Shopköp | Mekanik och avgränsning |
|---|---:|---:|---|
| Accelerant | 0/132 | 47 | Extra gifttick. Första exemplaret får butikens skalning när leken kan börja lägga gift. Bubble Bubble ensam kan bara förstärka befintligt gift. |
| Accuracy | 0/110 | 10 | Extra skada per Shiv. Första exemplaret får skalningen med en tryckt Shiv-generator. |
| Phantom Blades | 0/113 | 11 | Extra skada på första Shiv varje tur. Samma villkor. |
| Infinite Blades | 0/118 | 17 | Skapar själv en Shiv varje tur. Första exemplaret får butikens återkommande värde. |
| Afterimage / Well-Laid Plans / Tools of the Trade | 0/36, 0/51, 0/34 | 0, 0, 0 | Utlöst block, behållen hand respektive drag/discard per tur saknas i grundvärdet. Ingen motsvarande serie shopköp i denna panel. |
| Noxious Fumes / Footwork | 59/114, 46/119 | 57, 1 | PoisonPerTurn respektive DexterityPower finns redan i grundvärdet. |
| Corrosive Wave / Mirage / Serpent Form | 0/41, 0/133, 0/50 | 0, 0, 0 | Gift per drag, block från fiendens gift och skada per kortspel saknar egen term i gratisvärdet. Mirage visar noll beräknat block utanför strid. |
| Envenom / Outbreak | 0/38, 35/36 | 0, 1 | EnvenomPower får ett statiskt setupvärde, utan antalet träffar som kan lägga gift. Outbreak får ett direkt giftvärde. |
| Acrobatics / Backflip | 0/111, 76/345 | 0, 9 | Det numeriska draget finns i båda grundvärdena, och Backflip får dessutom block. |
| Calculated Gamble / Speedster | 0/106, 0/107 | 1, 0 | Ett helt handbyte respektive skada vid drag fångas dåligt. Köpunderlaget är tunt. |

Draftflaggan återanvänder butikens befintliga, akt- och kostnadsjusterade skalningsterm för de fyra första korten som tillägg till grundvärdet. Det värdet går genom både grundpoängen och modellens `take:value`. Effekten på totalpoängen per extra råpoäng är 0,35 + 0,55 × (−1,54747)/10 ≈ 0,26489. På de oförändrade v5-händerna matchade referensen varje sparat val vid ompoängsättningen. Draftflaggan valde Accelerant i 71/132, Accuracy i 35/110, Phantom Blades i 47/113 och Infinite Blades i 100/118. Av de 71 Accelerant-valen ersatte tolv skip och 59 ett annat kort, bland annat sju Snakebite. För Infinite Blades ersatte 80 av 100 ett annat kort. Siffrorna gäller de historiska händerna. Den parade dev-panelen mäter hur de senare lekarna och runutfallen faktiskt förändras. Utfallet av draftarmen kan inte tillskrivas Accelerant ensamt.

### Bosstaktik när v2-sökning faller tillbaka

- **The Insatiable.** V5:s `cheap`-plan reserverade energi vid högst tre Sandpit för en Escape som kostar ett, men först vid ett för en dyrare Escape. V5.1 flyttar dessa gränser till fyra respektive två. Vid två räcker en extrapolerad skadehastighet inte för att släppa reservationen. Säkra dödande träffar, dödligt befintligt gift och omedelbart överlevnadsbehov har fortsatt prioritet. I de 16 historiska förlusterna med Sandpit på ett var Escape spelbar **noll gånger under själva dödsrundan**. Nio av 16 hade en spelbar Escape i rundan före, och sex av de nio spelade redan minst en. Det begränsar vad en tidigare reservation ensam kan rädda.
- **Knowledge Demon.** Sloth begränsar spelaren till tre kort per runda. Det publika fältet `amount` är taket. Policyn räknar utförda spelarkommandon under Sloth och nollställer per runda. Den jämför kortens nytta med energi per återstående plats, tar bort gratisbonus och begränsar nyttan av skapade Shivs och drag som behöver följdspel. Överlevnadsplaner får som mest använda det återstående antalet manuella kort och kan använda drycker separat. I de 51 historiska baskortsvalen i förluststriderna fanns ett lagligt icke-baskort vid 36 och en spelbar power vid tre. Motorns `can_play` avgör vad som faktiskt går att spela. Automatiska spel kan göra den observerade återstående budgeten till en övre gräns.
- **Queen.** I den faktiska stridsobservationen har Torch Head Amalgam Minion och lämnar striden när ledaren dör. Legacy sänker minions skadevärde och räknar med att ett ledardödande spel också undanröjer minionens attack. I sex dödsstrider levde båda vid döden, och v5 angrep båda målen (33/12). Det stöder att direkt skada på Queen kan vara rätt. Materialet visar inget generellt målprioritetsfel och ingen Queen-regel ingår.

V2 får det frysta legacyförslaget i sin sökning. Bosstaktiken får påverka utförd handling först vid fallback eller när legacy själv styr. [Frysta beslut och dödsstrider](silent-a10-v5-lategame-autopsy.md)

### Makro

- **This or That?** Plain kostar 6 HP och ger 41–68 guld. Spelets `ThisOrThat.CalculateVars` drar `NextInt(41, 69)`. Samma spann syntes i de 75 historiska erbjudandena. Ornate ger en slumpmässig relik och Clumsy. V5 upptäcker redan både relik och förbannelse genom beskrivningen. Den fasta förbannelsevikten saknar senare removalutgifter. I autopsin betalade policyn 3 200 guld efter de 75 valen, i snitt 42,67 guld per Ornate. V5.1 räknar denna observerade utgift i eventmodellens enheter (75 guld per poäng) när Plain lämnar minst v5:s normala vilogräns, 77 % HP, och spelaren kan ta emot guld. Eventmodellen jämför därefter båda alternativen. I de sparade v5-erbjudandena skulle tolv val ha bytt till Plain. Utgiften är observerad. Det alternativa nettovärdet av att avstå från reliken kräver en jämförelse av runutfall.
- **Ancient.** Ruttens Bellman-jämförelse tillät ett direkt hopp till rad ett när rad noll också var laglig. De två dokumenterade fallen gick miste om ett helt relikval. Makroflaggan väljer den lagliga Ancient-rutan på rad noll vid ingången till Act 2 eller 3.
- **Eld.** V5 valde mellan vila och smide vid 77 % HP i championpaketet. I den historiska gruppen vid sista Act 2-elden var det framför allt redan skadade lekar som vilade (10/84 clears), medan friskare lekar smidde (7/20). Detta ger ingen skattning av vinsten av att flytta tröskeln. Den riktade ändringen använder redan provad Kindle-logik när v5 vill smida och Pumpkin Candle har noll laddningar i Act 2–3. Policyvalet mellan Philosopher's Stone och Velvet Choker ingår inte i flaggan.

## Mätning och reproduktion

`3f79519d6aed5e4e8d6549cd8e02d001e28d21d8` frös policykod, insamlare, alla fem armar och alla 256 ordnade tripplar innan första dev-processen startade. Panelens SHA-256 är `53b6f1cb00bf63aeb33069451b97fa0b62b5e045237dc82f1d497f4135c71b43`, över kompakt JSON med `[index, seed, läge]`. Jämna index använder default, udda seeded. Varje arm använder makroslump 7103 + samma index och en ny native-process per lobby. Insamlaren godtar bara den exakt låsta panelen och kontrollerar mängdskärningen med de 896 officiella seednamnen. Prefixet är disjunkt från V5DIAG, V5DEV, M4 och CSV. Som separat kontroll gav spelets UTF-8/xxHash64 också 256 olika värden och noll kollisioner mot de 896 officiella seednamnen, de 640 tidigare V5DIAG/V5DEV-namnen och 4 916 registrerade CSV-namn från fas 2–3.

Slutvåning är `17 × (akt − 1) + lokal våning` enligt v5-protokollet. W/L/T räknar högre, lägre och lika slutvåning för samma seed och aktlisteläge jämfört med v5. Det tvåsidiga percentilintervallet bygger på 10 000 parade bootstrapomdragningar inom de två aktlistelägena, med den förregistrerade RNG-seeden 510024. Intervallen är marginala per arm. Bossutfall anges både per start och för de lobbys som faktiskt nådde respektive boss. A3-entré räknar en lobby en gång även om den möter båda bossarna. En full vinst kräver nativ seger efter två olika Act 3-bossvåningar.

Ett gratiserbjudande räknas en gång per kort-ID och belöningsbeslut utanför strid. Ett shopbesök räknas som ett köptillfälle om kortet vid något beslut är i lager och spelaren har råd. Sandpit avläses precis före utfört `end_turn`. Ett sådant slut är fatalt om nästa nativa svar är förlustterminalen. Sloth-måttet räknar utförda manuella kortspel när kraften är aktiv, inklusive eventuella sökbeslut. JSON redovisar dessa mått för alla möten och separat för förluststriderna. Fullständiga lobbykvitton gör att även parade delmängder kan räknas om.

På omarchy används den förberedda Linux-hosten och spelets DLL från v5-autopsin. Insamlaren verifierar SHA-256 för båda samt för championmanifestet. Om råkatalogen ska återskapas kan följande köras från reporoten med lokala spelassets, SDK och matchande byggd host. Packningen läser sparade V5DIAG-observationer för den historiska ompoängsättningen och jämför v5 med makro- respektive bossarmen på samma publika tillstånd i varje par där beslutshashen skilde sig. Hela referensförloppet återspelas och kontrolleras mot sin sparade beslutshash. Den sista rapportkommandoraden återskapar JSON från incheckade kvitton utan spelet. [Bygginstruktioner för Linux-hosten](silent-a10-v5-lategame-autopsy.md)

```sh
export PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
.venv/bin/python scripts/collect-v51-autopsy.py --output artifacts/v51-reproduction --workers 8
.venv/bin/python scripts/report-v51-autopsy.py --from-run artifacts/v51-reproduction
.venv/bin/python scripts/report-v51-autopsy.py
```

Varje v5.1-arm går att ladda med `load_bundle` och `DeployedController.from_bundle`. För egen användning kan man kopiera championmappen och sätta önskade booleska nycklar på toppnivå i kopians `policy.json`. Insamlaren gör motsvarande med `freeze_bundle`. Payloadfilerna behåller sina SHA-256.

## Bakåtkompatibilitet och verifiering

- Alla tio arbetskopiefiler i championmappen matchar Git-blobbarna vid `efd9877`. Träd-ID är `4dbea285741125c118a5cef42783a36cc12f8eb0`. Även alla 13 källfiler i `combat_search_v2/` matchar, med träd-ID `ab8a47900d8afc24e8ac217e7250fbe7c047cdd4`.
- Originalbyggaren har 15 profilnamn inklusive båda sökvarianterna. Testet bygger alla 15 och jämför manifestets bytehash med en separat byggning ur en arkiverad `efd9877`-källkopia. Laddaren verifierar varje refererad payload mot dess SHA-256. I de fyra nya armarna är samtliga nio modell- och konfigurationsfiler identiska med v5. Bara de begärda toppnivåflaggorna läggs till i manifestet.
- Med tre explicit avstängda flaggor matchade alla 580 handlingar och efterföljande svarsdigester i det incheckade vinstkvittot för `V5DIAG_0100`. På den nya panelen kördes dessutom `efd9877`-källans ursprungliga `DeployedController` oberoende på `V51DEV_0000` och `V51DEV_0001`. Båda matchade referensarmens hela beslutshash och terminalutfall. Sju kontrollåterspelningar genom de aktiverade armarnas driftsättningsgränssnitt matchade också evaluatorns hela beslutshash och utfall.
- De nya räknarna applicerades på gamla sparade v5-beslut. De återgav 0/132 gratisval, 47 butiksköp, 16 fatala Sandpit-avslut på ett, 51/177 Sloth-baskort i förluststrider, 75 Ornate, 32 Clumsy-removals till 3 200 guld samt 46 lagliga Kindle. De direkta återspelningarna och de historiska kontrollerna ingår inte i ablationens 1 280 starter.
- På omarchy passerade `.venv/bin/pytest -q` **495 tester**, med `CSV2DEV_HOST` och `CSV2DEV_OBSERVER` satta till samma lokala native-host och Phase 2-testobservatör som i v5-autopsin. `.venv/bin/ruff check src/ tests/` gav noll anmärkningar. [Tester för v5.1](../../tests/test_v51_autopsy_fixes.py)
