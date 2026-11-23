# Silent A10 · vad dödade fryst v5 i slutet av runnen?

**Fryst `all_v2_search_v5` vann en verifierad tvåboss-run på omarchy.** Av 384 färska starter nådde 104 Act 2-bossen, 17 klarade den, nio nådde Act 3-bossen och en slog båda bossarna. De 87 Act 2-bossdödsfallen hade typiskt mer än hundra fiende-HP kvar. Alla 103 sena dödsfall hade tomt dryckesbälte. Den starkaste uppmätta skillnaden var hur mycket HP Silent hade kvar **när Act 2-bossstriden började**.

| Färsk panel | Starter | Act 1 clear | Act 2 boss | Act 2 clear | Act 3 boss | Full vinst |
|---|---:|---:|---:|---:|---:|---:|
| Default | 192 | 126 | 60 | 8 | 4 | 1 |
| Seeded | 192 | 117 | 44 | 9 | 5 | 0 |
| Totalt | 384 | 243 | 104 | 17 | 9 | 1 |

Den officiella Windows-verifieringen gav 44/234 Act 2-clears och 0/896 vinster. Här gav Linux-panelen 17/104 (16,3 %) och 1/384 (0,26 %). Panelerna har olika seeds, aktlistemix och plattformsbyggen. 95-procents Wilsonintervall för 1/384 är 0,05–1,46 %. [Officiell verifiering](../combat-search-v2/v5-release-report.md)

## Den vinnande runnen

`V5DIAG_0100`, default och makroindex 100, nådde The Insatiable med 81/81 HP, två drycker och 36 kort. Leken hade fyra Snakebite, två Accelerant och Snecko Skull. Vid Queen hade spelaren 77/81 HP, 52 kort, elva uppgraderingar, Royal Poison och Lizard Tail. Queen föll på våning 15 i runda 6. På våning 16 gick Silent in med 22/81 HP och Fairy in a Bottle, spelade Accelerant i runda 2 och besegrade Aeonglass i runda 7. Den enskilda runnen illustrerar samspelet mellan gift, uthållighet och resurser över två bossar.

Två nya körningar med samma frysta policy reproducerade originalets sparade beslut och native victory efter 580 spelarbeslut. Med och utan diagnostikmodulen blev samtliga 629 RPC-kommandon och svarsdigester identiska, även det terminala svaret. Även en separat körning direkt genom `DeployedController.choose/observe` matchade alla 580 spelarbeslut och deras svar. Vinstkvittot innehåller den fulla kommandoföljden. [Vinstkvitto](silent-a10-v5-win-V5DIAG_0100.jsonl.gz)

## 1. Hur nära var dödsfallen?

HP och dödsrunda kommer från den nativa motorn när Silent dör, efter den sista spelarhandlingen. Tabellen visar median [25:e–75:e percentil]. Skada ut/in är summerad faktisk oblockerad skada på fiendesidan respektive spelarsidan delad med det totala antalet påbörjade rundor i dödsstriderna. Överskada och blockerad skada ingår inte. Gift, passiva effekter och andra källor som registreras av spelet ingår. Direkt död från en mekanik kan ske utan en skadehändelse. Fördelningar per möte, min/max och spelarens start-HP finns i [JSON-rapporten](silent-a10-v5-lategame-autopsy.json).

| Möte | Döda/inträden¹ | HP kvar | Dödsrunda | Skada ut/r | Skada in/r |
|---|---:|---:|---:|---:|---:|
| Kaiser Crab | 32/35 | 231,5 [158–277,3] | 4 [4–6] | 43,68 | 10,59 |
| Knowledge Demon | 27/35 | 130 [66,5–162,5] | 7 [6–8] | 42,01 | 7,23 |
| The Insatiable | 28/34 | 128 [92,5–159,8] | 6 [5–7] | 37,37 | 6,55 |
| Queen | 6/7 | 258,5 [211,3–281,8] | 3,5 [3–4,8] | 61,67 | 11,46 |
| Test Subject | 1/1 | 4 | 2 | 53,50 | 25,50 |
| Aeonglass | 1/3 | 214 | 5 | 64,20 | 16,80 |
| Act 3-eliter | 3 döda | 202 [199–219,5] | 3 [2–3,5] | 34,12 | 11,50 |
| Act 3-hallways | 5 döda | 61 [45–68] | 4 [4–4] | 31,46 | 9,12 |

¹ Bossinträden räknas per faktiskt öppningsmöte. Nio Act 3-bosslobbyer gav elva bossstrider. Kaiser och flerfienderum summerar levande fiender. Queen visar drottningens HP, medianen inklusive Torch Head var **381**. Test Subject hade **4 av 111 HP på den första stapeln**, med Adaptable kvar. Nästa återuppståndelse återstod.

Bara **6/87** Act 2-bossdödsfall hade högst 25 HP kvar, två per boss. Medianerna motsvarade 54 % av öppnings-HP för Kaiser, 33 % för Knowledge Demon och 38 % för The Insatiable. I Act 3 dog två mot riddartrion (202 och 237 HP), en mot Mecha Knight (196), tre mot Axebot (33–68), en mot Punch Construct med två Cubex (61) och en mot Owl Magistrate (104). Den lägsta spelarstarten i en fatal elitstrid var 2 HP.

## 2. Vad skilde däcken åt?

Mätpunkten är första offentliga beslutet i Act 2-bossstriden, före utfallet och före bossbelöningen. Ett värde per lobby. AUC här är sannolikheten att en slumpmässigt vald clear har högre värde än ett slumpmässigt valt dödsfall, med halv vikt vid lika. Det är ett deskriptivt mått i denna panel.

| Vid bossinträde | Clear, n=17, medel | Död, n=87, medel | AUC |
|---|---:|---:|---:|
| HP / max-HP i absoluta tal | 67,8 / 77,8 | 52,0 / 74,7 | 0,757 för HP |
| Andel HP kvar | 87,2 % | 69,9 % | 0,751 |
| Kort / uppgraderingar | 28,65 / 4,65 | 28,40 / 5,15 | 0,511 / 0,448 |
| Powers / Accelerant-kopior | 1,59 / 0,59 | 1,17 / 0,22 | 0,621 / 0,646 |
| Giftkällor / AoE-kort | 5,24 / 2,76 | 4,74 / 2,72 | 0,554 / 0,513 |
| Andel kort med block | 26,8 % | 26,0 % | 0,547 |
| Reliker med energi- / drageffekt | 0,76 / 1,53 | 1,03 / 1,49 | 0,420 / 0,475 |
| De sex efterfrågade skalningskorten, kopior | 0,59 | 0,64 | 0,486 |

**HP skilde grupperna åt även inom boss.** AUC för ingångs-HP var 0,974 för Kaiser (bara tre clears), 0,586 för Knowledge Demon och 0,863 för The Insatiable. Under 50 HP blev det 1/40 clears, vid 50–64 HP 6/31 och från 65 HP 10/33. HP fångar också tidigare stridskvalitet och relikeffekter.

**HP försvann framför allt i vanliga Act 2-rum på vägen.** Separata återspelningar av alla 104 bossentréer matchade ursprunglig dödsformation eller vinst, våning, bossvåningar och antal beslut. I de 87 bossförlusterna kostade vanliga strider sammanlagt **68,0 netto-HP per lobby** före bossen, mot **45,8** hos de 17 som klarade. Grupperna tog 4,90 respektive 4,65 sådana fighter och förlorade 13,88 respektive 9,86 HP per fight. Eliter kostade ytterligare 13,5 respektive 10,2 per lobby. Nettokostnad här är spelarens HP vid första stridsbeslut minus HP vid första observation efter striden, inklusive eventuell direkt läkning.

Bland vanliga formationer med minst fem observationer var Bowlbug Rock + Bowlbug Silk + Slumbering Beetle dyrast per möte (24,4 HP, n=21), följt av Hunter Killer (21,5, n=28). Två Chomper stod för störst sammanlagd hallway-förlust (688 HP på 38 möten). Entomancer och Infested Prism kostade 42,9 respektive 39,5 HP per elitmöte, båda n=13. Mätningen omfattar bara lobbys som senare nådde bossen. En rutt kan även vinna guld, kort eller reliker på det dyrare mötet.

**Accelerant var den tydligaste däcksignalen bland de redovisade måtten.** 8/24 lekar med kortet klarade bossen, mot 9/80 utan. Från 65 HP var motsvarande tal 6/10 mot 4/23, under 65 HP 2/14 mot 5/57. Små grupper och självselektion gör detta till en hypotes. Fria belöningar erbjöd Accelerant **132 gånger och valde det noll gånger**, varav 20 rena skips. Vid 95 erbjudanden fanns redan minst en tryckt giftkälla, inklusive 14 av de rena skipsen. Shoppen köpte det 47 gånger och samtliga köpare hade en tryckt giftkälla i leken. Bland bossinträden utan Accelerant hade 24 lobbys tidigare fått ett gratis erbjudande om kortet, och 21 av dessa dog.

Footwork förekom i 2/17 clears och 12/87 dödsfall, Noxious Fumes i 6/17 och 30/87, Accuracy i 1/17 och 8/87. Inget av bossdäcken hade Afterimage, Well-Laid Plans eller Catalyst. På hela panelen valdes Afterimage 0/36 gånger, Well-Laid Plans 0/51 och Accuracy 0/110 i fria belöningar. Catalyst hade noll erbjudanden där. Block räknar tryckta positiva blockvärden, AoE text om alla fiender, giftkällor tryckt PoisonPower eller PoisonPerTurn. Reliker räknar observerade användbara energikällor samt tryckt extra kortdrag inklusive startreliken och villkorade effekter. Full kortlista med uppgraderingsnivå för varje sen strid finns i [run-kvittona](silent-a10-v5-autopsy-runs.jsonl.gz).

## 3. Reliker, drycker och makrobeslut

**Bossrelikerna väljs i Ancient-eventet på nästa akts första våning.** Efter Act 1 besökte 241/243 Ancient, efter Act 2 alla 17/17. I två verifierade återspelningar, `V5DIAG_0007` och `V5DIAG_0274`, gick routern direkt till ett monster på rad 1 trots att Ancient på rad 0 var lagligt. Därmed gick båda miste om hela relikvalet. Vilka tre reliker de hade fått visades aldrig. Efter Act 1 tog v5 bland annat Pael’s Tears 22/29 erbjudanden (0 av 22 nådde Act 3), Touch of Orobas 21/38, Very Hot Cocoa 20/26 och Pael’s Flesh 19/27. Drageffekten Pael’s Blood togs 4/27, Snecko Eye 1/7 och Runic Pyramid 0/4. Tears kräver att energi lämnas oanvänd vid rundans slut. Med reliken avslutade v5 23/44 observerade Act 2-bossrundor med energi kvar. Utfallet för de andra relikerna i samma erbjudanden kräver parat prov.

Philosopher’s Stone togs **13/13**, varav en nådde Act 3. Texten ger alla fiender Strength. V5 använder det positiva värdet i samma term som spelarens Strength och ger därmed +2 i grundpoäng per Strength. Efter Act 2 tog v5 bland annat Whispering Earring 3/3, Blood-Soaked Rose 2/2 och Brilliant Scarf 1/3. Örhänget ger energi men överlåter första rundan åt Vakuu. Så små urval räcker bara för att identifiera beslut att återspela. Varje erbjudet, valt och bortvalt alternativ finns i kvittona.

**Dryckerna tog slut.** Av 87 fatala Act 2-bossfighter började 21 med tomt bälte, 41 med en dryck och 25 med två. V5 drack 73 av 90 manuellt använda drycker redan i runda 1. Åtta fatala Act 3-bossfighter började med 0/1/2 drycker i 2/2/4 fall, med åtta av tio manuella användningar i runda 1. Alla 87 + 16 sena dödsfall hade noll drycker både före fatal handling och vid död. Automatiska effekter kan förbruka en dryck utan `use_potion`. Den mätbara frågan för nästa försök är vilka öppningsdrycker som hade högre värde en runda senare.

| Alla starter, beslut per akt | Act 1 | Act 2 | Act 3 |
|---|---:|---:|---:|
| Rest / Smith | 765 / 442 | 319 / 92 | 23 / 11 |
| Shop, kort / relik / dryck | 407 / 94 / 172 | 119 / 108 / 112 | 14 / 9 / 9 |
| Betalda removals | 93 | 47 | 13 |
| Utgång med removal fortfarande köpbar | 43/516 | 39/251 | 0/20 |

**Campfire.** Vid sista Act 2-elden vilade 84 bossentréer och 10 klarade bossen. 20 smidde och sju klarade. Grupperna kom till elden med median 26,5 respektive 66,5 HP. Vila gav median 22 HP och alla 1 107 valda vilor under panelen gav faktisk läkning. Pumpkin Candle togs 17/17 efter Act 1. Kindle var lagligt 46 gånger och valdes aldrig. Med helt slocknat ljus vilade v5 tolv gånger och smidde tre. Det senare är en konkret möjlighet att återställa extra energi på en eld där policyn bedömt att läkningen kan avvaras.

**Shop och event.** De 153 betalda borttagningarna tog bland annat bort 51 Defend, 35 Strike och 32 Clumsy. Alla 32 Clumsy följde på att samma run hade valt Ornate i *This or That?*. Dessa köp kostade sammanlagt **3 200 guld** i listade removalpriser. Ornate valdes 75/75 och gav både en slumpad relik och en Clumsy. Plain kostar HP och ger guld. Det gör båda alternativen värda att pröva vid hög HP. Andra direkta skulder var Guilty från Neow’s Sacrifice 36 gånger, Greed från Cursed Pearl 31 och Poor Sleep från Unrest Site tolv. De största synliga omedelbara HP-kostnaderna vid själva eventvalet var Tablet of Truth, sammanlagt 9 HP över tre Decipher-val, och Abyssal Baths, 1 HP. Senare stridskostnad för förbannelser ingår inte i dessa HP-tal. Shoppen köpte ofta Noxious Fumes (57), Accelerant (47) och Poisoned Stab (36). Det finns tydligare stöd för att fria belöningar missar skalning än för att de vanligaste butiksköpen är svaga.

## 4. Vad gjorde legacy i dödsstriderna?

Sökningen täckte 280/3 149 behöriga Act 2-bossbeslut (8,9 %) och 17/1 620 Act 3-beslut (1,0 %), räknat över både vunna och förlorade fighter. Behörighet följer releaseprotokollet. Nedan gäller siffrorna de fatala striderna.

- **Kaiser Crab.** V5 riktade 223 attacker mot Crusher och 141 mot Rocket. Båda levde vid 28/32 dödsfall. Med båda vid liv slutade bara 1/152 rundor med den starkare justerade attacken i ryggen och sammanlagd visad skada som översteg block. Måttet följer sista explicita mål och startläget mot Rocket, korrigerar bakattack med faktor 1,5 och exkluderar Intangible. Det säger inget om en alternativ kortsekvens är laglig eller dödlig. Fokusskada över flera rundor är en bättre hypotes än ett generellt byte av slutriktning.
- **Knowledge Demon.** Policyn väljer Sloth i det fasta förbannelsevalet. Sloth var aktiv i 63 rundor och minst tre kort spelades i 52. Strike/Defend stod för 51 av 177 spel i dessa rundor. Varje sådant kort konkurrerar om en av tre platser. Att ett baskort spelas bevisar inte att handen erbjöd ett bättre alternativ.
- **The Insatiable.** V5 avslutade den fatala rundan med Sandpit på ett i 16/28 fall. I tolv av dessa var summan av de visade attackerna mindre än spelar-HP plus block. Frantic Escape spelades totalt 37 gånger i förluststriderna. Följ energin och den återstående tiden en runda tidigare vid fortsatt test.
- **Queen och Test Subject.** Av 45 riktade attacker mot Queen-formationen gick 33 till drottningen och tolv till Torch Head. Båda levde vid alla sex dödsfall. Fem inträffade på första bossvåningen, ett på andra. Test Subject fick sex Skill-spel under Enrage före döden i runda två. Det finns för lite stöd för en generell målprioritets- eller Skill-spärr.
- **Tidiga powers.** I fatala Act 2-bossfighter med en spelbar power någon gång i runda 1 eller 2 spelade v5 minst en sådan i 28/40 berörda rundor. För Act 3-bossar var siffran 3/4, eliter 2/2 och hallways 0/1. Sex missade rundor hos Kaiser är värda handgranskning. Exponeringen var liten för övriga Act 3-grupper.

## 5. Prioritering mot upprepade Act 3-vinster

Ordningen väger antalet exponerade lobbys mot hur direkt mekanismen är observerad. Räkneexemplen visar storleksordningen per 384 starter. Endast dev-prototypen har ett uppmätt parat policyutfall. För att översätta extra Act 2-clears till en grov vinstskala används den mycket osäkra observerade konverteringen 1/17.

| Rang | Område och nästa försök | Möjlig effekt på Act 2 och Act 3 |
|---:|---|---|
| 1 | **Makro, vägval och HP.** Testa en vägpolicy som prioriterar hälsa fram till sista elden, särskilt inför Kaiser. Mät bossinträden och ingångs-HP tillsammans så att policyn inte bara sorterar bort svaga runs. | Om tio av de 40 ingångarna under 50 HP kunde flyttas till minst 65 HP och fick den gruppens clearfrekvens, motsvarar skillnaden 2,8 ytterligare clears och 0,16 vinster. Tidigare stridskvalitet kan förklara en del av sambandet. |
| 2 | **Makro, draft och shop.** Testa det första gratisexemplaret av Accelerant när leken redan har fungerande giftkällor. Mät även vad som väljs bort och om guld då kan användas till relik eller removal. | 21 bossdödsfall saknade Accelerant trots ett tidigare erbjudande. Tio exponeringar med den observerade skillnaden 8/24 mot 9/80 motsvarar 2,2 clears eller 0,13 vinster. Den starkaste giftleken stod för panelens enda vinst. |
| 3 | **Bosstaktik.** Prioritera Frantic Escape medan det ännu går att betala, och värdera varje kortplats efter Sloth. Lämna kvalificeringen av dessa strider till det parallella Helmer-spåret. | Tolv Insatiable-dödsfall hade Sandpit på ett utan synligt dödligt attackintent. Om en fjärdedel av dessa kan räddas ger det 3 clears eller 0,18 vinster. En säkerhetsmarginal för felriktning hos Kaiser har betydligt färre observerade tillfällen. |
| 4 | **Flertursvärde i Act 3.** Värdera Queen-skada, miniontryck, återupplivning och kvarvarande HP inför andra bossen. Jämför även tidig mot senare dryckesanvändning i identiska öppningar. | Påverkar Act 3 direkt. En av de sex Queen-förlusterna inträffade på andra bossvåningen och skulle ensam ge en ytterligare full vinst om den vändes. De fem övriga behöver fortfarande slå nästa boss. |
| 5 | **Små Ancient- och campfirefel.** Testa rätt mottagare för Strength och Kindle på en slocknad Candle när v5 tänker smida. | På diagnostikpanelen omfattade de avgränsade reglerna 13 Stone-erbjudanden och tre möjliga byten från Smith. Den separata parade mätningen nedan avgör hur mycket detta faktiskt ändrade utfallet. |

## Opt-in och parad prövning

`v6_lategame_fixes=True` vänder tecknet på Strength-termen för Philosopher’s Stone och väljer laglig Kindle före Smith enbart med Candle på noll laddningar i Act 2–3. Normal vila behåller sin prioritet. Båda ändringarna går genom samma inställning i evaluator och `DeployedController`. Prototypen frystes i `742a4c1` före dev-panelen. Dev jämför det gemensamma ingreppet med fryst v5. Första ändrade makrobeslut binds till samma publika tillstånd i de två armarna. [Parade kvitton](silent-a10-v5-autopsy-pairs.jsonl.gz)

| 256 par, 128 per aktlisteläge | Fryst v5 | Prototyp |
|---|---:|---:|
| Act 2-boss / clear | 71 / 17 | 71 / 17 |
| Act 3-boss / full vinst | 3 / 0 | 2 / 0 |
| Global medelvåning | 24,0469 | 24,0078 |

**Behåll prototypen avstängd.** Den parade skillnaden var −0,0391 våningar, med 10 000 parade bootstrapomdragningar inom aktlisteläge och intervall [−0,1172, 0,0000] vid 95 %. Antal högre/lägre/lika slutvåningar var 0/1/255. Act 2-clears var samma 17 lobbys, åtta default och nio seeded. Fem par hade ett första ändrat val i samma publika tillstånd. Två bytte Smith mot Kindle och tre bytte Stone mot Sozu, Ectoplasm respektive Velvet Choker. Hela våningsförlusten kom från Choker-bytet på `V5DEV_0201` (Act 3 våning 15 → 5). Devutfallet räcker inte för att rangordna de tre ersättningsrelikerna.

250 par hade exakt samma hash över samtliga spelarbeslut och föregående publika tillstånd. Ett sjätte par, `V5DEV_0167`, hade olika publika digester vid Trial, samma 22 registrerade event-/eldval på samma steg, samma 536 beslut och samma slut mot Axebot på Act 3 våning 13. Orsaken till digestskillnaden är oidentifierad. Båda originalutfallen ingår. Alla 512 starter i devjämförelsen och alla 384 diagnostikstarter avslutades utan omstart eller övergiven run.

## Panel, mätning och reproduktion

Arbetskopian var ren före byte till `origin/codex/a10-v2-tactics` vid `efd98778688eac038cc946693cadd4389cb30d4d`. Samtliga lobbys startade en ny native-process för Silent solo A10. Utgången kom från den vanliga release-evaluatorns spelcykel. Spelaren ser enbart de ordinarie observationerna. En skrivande observatör på motorns `CombatHistory.DamageReceived` och `Hook.BeforeDeath` gav per-handlingskvitton utanför policyprocessen. Den slutliga dödsrundan och varje enskild fiendes HP knöts till samma exekverade steg. Vid start använder rapporten den första synliga spelarsituationen, inklusive effekter som redan triggats när rummet öppnades. Även två diagnostiska förlustlobbys, en per aktlisteläge, gav identiska hashkedjor över beslut med och utan observatör.

- Diagnostikordningen är `V5DIAG_0000`–`V5DIAG_0383`, devordningen `V5DEV_0000`–`V5DEV_0255`. Jämna index kör default och udda seeded. Makroslumpens seed är 7103 + index. SHA-256 av kompakt JSON över ordnade `[index, seed, läge]` låstes före respektive första start. Diagnostikens hash är `88993f46d0d41700e6014af5cf0079754dbb7ae2794e34c8ca63b0e0b5e2a51e` och devpanelens `bbd4a073745a3b0a3c37ba3c36b81cea6647c6c47ffde6a871cbd2f572c72916`. De förseglade serierna användes enbart som historisk sammanfattning.
- Linux-hosten byggdes i privat katalog med branchens patchar mot `fec723a`. Spel-DLL `f4da33f4…a29a70b`, host `f640ffd8…1d89a00`, fryst policymanifest `a686db12…c81fcb`. Fullständiga SHA-256, panelstorlekar, kvittoidentiteter, enskilda utfall och samtliga maskinläsbara tabeller ingår i [sammanfattningen](silent-a10-v5-lategame-autopsy.json).
- JSONL-kvittona innehåller alla 384 terminaler och makroval samt alla 104 Act 2-bossstrider och 81 Act 3-strider. De innehåller däck med uppgraderingar, reliker, bälten vid in- och utgång, varje sen handling med mål, fiende-HP och visad attack, native-dödsögonblicket samt skadesummor. Gold/HP-delta vid makroval avser den närmast följande observationen. Ett nytt köpförslag efter ett faktiskt köp räknas som ett nytt beslut. `leave_room` räknar butiksutgångar. För uppgifter om erbjuden/vald/bortvald relik används endast lagliga alternativ.

Från en förberedd Linux-checkout med lokala spelassets kan den kompletta sammanfattningen återskapas från de incheckade kvittona med `.venv/bin/python scripts/report-v5-autopsy.py`. För ny insamling på samma diagnostiklobbys används följande från reporoten med en ny `artifacts/v5-autopsy`-katalog. Rapporteringen kräver NumPy, insamlingen även spelet och .NET.

```bash
export PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
.venv/bin/python scripts/build-silent-host.py --output artifacts/v5-autopsy/native-host
artifacts/tools/dotnet/dotnet build scripts/headless/lategame-observer \
  -p:GameLib="$PWD/artifacts/upstreams/sts2-cli/lib" \
  --source "$PWD/artifacts/v5-autopsy/native-host/empty-feed" --disable-build-servers
.venv/bin/python scripts/collect-v5-autopsy.py --panel V5DIAG --workers 8
.venv/bin/python scripts/verify-v5-autopsy-win.py
.venv/bin/python scripts/replay-v5-approaches.py
.venv/bin/python scripts/collect-v5-autopsy.py --panel V5DEV --workers 4
.venv/bin/python scripts/collect-v5-autopsy.py --panel V5DEV --workers 4 --fix
.venv/bin/python scripts/reduce-v5-autopsy.py
.venv/bin/python scripts/reduce-v5-autopsy.py --dev
.venv/bin/python scripts/report-v5-autopsy.py
```

På omarchy passerade **476/476 tester** med Linux-hosten och Phase 2-testobservatören aktiverade. Ruff rapporterade noll anmärkningar i `src/` och `tests/`. Samtliga tio arbetskopiefiler i det frysta championpaketet jämfördes byte för byte med Git-blobbarna vid `efd9877`. Träd-ID var `4dbea285741125c118a5cef42783a36cc12f8eb0`. Källträdet för `combat_search_v2` matchade också bascommiten.
