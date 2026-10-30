// Opt-in local integration probe; requires the user's pinned game assembly.
// Reflection is restricted to setting test fixtures / inspecting test invariants.
// None of these controls are added to the policy protocol or training records.
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Runs;
using Sts2Headless;

class Program
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static int Main(string[] args)
    {
        var root = Path.GetFullPath(args[0]);
        var lib = Path.Combine(root, "artifacts/upstreams/sts2-cli/lib");
        Environment.SetEnvironmentVariable("STS2_LIB", lib);
        Environment.SetEnvironmentVariable("STS2_GAME_DIR", lib);
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var path = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        };
        // Every execution gets its own save sandbox; never the installed game.
        var sandbox = Path.Combine(root, "artifacts/headless/observation-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(sandbox);
        Directory.SetCurrentDirectory(sandbox);
        Environment.SetEnvironmentVariable("APPDATA", sandbox);
        Environment.SetEnvironmentVariable("LOCALAPPDATA", sandbox);
        try { Run(sandbox); return 0; }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }

    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
    static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    static JsonElement Observe(RunSimulator sim) => Json(typeof(RunSimulator)
        .GetMethod("DetectDecisionPoint", Private)!.Invoke(sim, null)!);
    static JsonElement Relic(JsonElement obs, string id) => obs.GetProperty("player")
        .GetProperty("relics").EnumerateArray().Single(r => r.GetProperty("id").GetString() == "RELIC." + id);

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Run(string sandbox)
    {
        var sim = new RunSimulator();
        try
        {
            var start = Json(sim.StartRun("Silent", 10, "S2OBSCOUNTERS001", "en"));
            Check(start.GetProperty("type").GetString() != "error", start.ToString());
            var run = (RunState)typeof(RunSimulator).GetField("_runState", Private)!.GetValue(sim)!;
            var player = run.Players[0];
            var relics = (List<RelicModel>)typeof(Player).GetField("_relics", Private)!.GetValue(player)!;
            var nunchaku = (Nunchaku)ModelDb.Relic<Nunchaku>().ToMutable();
            var flower = (HappyFlower)ModelDb.Relic<HappyFlower>().ToMutable();
            var nib = (PenNib)ModelDb.Relic<PenNib>().ToMutable();
            foreach (var relic in new RelicModel[] { nunchaku, flower, nib })
            {
                relic.Owner = player;
                relics.Add(relic);
            }
            var combat = Json(sim.EnterRoom("monster", "SHRINKER_BEETLE_WEAK", null));
            Check(combat.GetProperty("decision").GetString() == "combat_play", combat.ToString());
            // Fixture: next attack must activate both counter relics.
            typeof(Nunchaku).GetProperty("AttacksPlayed")!.SetValue(nunchaku, 9);
            typeof(PenNib).GetProperty("AttacksPlayed")!.SetValue(nib, 9);
            var before = Observe(sim);
            Check(Relic(before, "NUNCHAKU").GetProperty("counter").GetInt32() == 9, "Nunchaku counter");
            Check(Relic(before, "NUNCHAKU").GetProperty("counter_rule").GetProperty("remaining").GetInt32() == 1, "One attack remaining");
            Check(Relic(before, "PEN_NIB").GetProperty("counter_rule").GetProperty("effect_amount").GetInt32() == 2, "Pen Nib multiplier");
            var unknown = Relic(before, "RING_OF_THE_SNAKE");
            Check(unknown.GetProperty("counter_rule").ValueKind == JsonValueKind.Null, "No invented rule");
            Check(unknown.GetProperty("counter").ValueKind == JsonValueKind.Null, "No invented counter");

            // Repeated observations must not mutate state; hidden draw-order
            // permutations (including duplicate identities) must not be exposed.
            Check(before.GetRawText() == Observe(sim).GetRawText(), "Observation has side effects");
            var draw = player.PlayerCombatState!.DrawPile;
            var backing = (List<CardModel>)draw.GetType().GetField("_cards", Private)!.GetValue(draw)!;
            var originalOrder = backing.ToList();
            var duplicate = backing.GroupBy(c => c.Id).First(group => group.Count() > 1).First();
            duplicate.UpgradeInternal();
            duplicate.FinalizeUpgradeInternal();
            var withUpgrade = Observe(sim);
            backing.Reverse();
            Check(withUpgrade.GetRawText() == Observe(sim).GetRawText(), "Hidden draw order leaked with modified duplicates");
            backing.Clear();
            backing.AddRange(originalOrder);
            before = Observe(sim);

            var attack = before.GetProperty("hand").EnumerateArray().First(c =>
                c.GetProperty("type").GetString() == "Attack" && c.GetProperty("cost").GetInt32() == 1
                && c.GetProperty("can_play").GetBoolean());
            var after = Json(sim.ExecuteAction("play_card", new() {
                ["card_index"] = attack.GetProperty("index").GetInt32(), ["target_index"] = 0,
            }));
            Check(after.GetProperty("decision").GetString() == "combat_play", after.ToString());
            Check(after.GetProperty("energy").GetInt32() == before.GetProperty("energy").GetInt32(), "Attack did not refund one energy");
            Check(Relic(after, "NUNCHAKU").GetProperty("counter").GetInt32() == 0, "Nunchaku did not wrap");
            Check(Relic(after, "PEN_NIB").GetProperty("counter").GetInt32() == 0, "Pen Nib did not wrap");
            Check(before.GetProperty("enemies")[0].GetProperty("hp").GetInt32() - after.GetProperty("enemies")[0].GetProperty("hp").GetInt32() == 12, "Pen Nib did not double Strike damage");
            Check(after.GetProperty("discard_pile").GetArrayLength() == before.GetProperty("discard_pile").GetArrayLength() + 1, "Played card not in discard");

            typeof(HappyFlower).GetProperty("TurnsSeen")!.SetValue(flower, 2);
            var beforeTurn = Observe(sim);
            Check(Relic(beforeTurn, "HAPPY_FLOWER").GetProperty("counter_rule").GetProperty("remaining").GetInt32() == 1, "Flower remaining");
            var nextTurn = Json(sim.ExecuteAction("end_turn", null));
            Check(nextTurn.GetProperty("decision").GetString() == "combat_play", nextTurn.ToString());
            Check(nextTurn.GetProperty("energy").GetInt32() == nextTurn.GetProperty("max_energy").GetInt32() + 1, "Flower did not grant energy");
            Check(Relic(nextTurn, "HAPPY_FLOWER").GetProperty("counter").GetInt32() == 0, "Flower did not wrap");
            var exhausted = Json(sim.ExecuteAction("end_turn", null));
            Check(exhausted.GetProperty("exhaust_pile").EnumerateArray().Any(c => c.GetProperty("id").GetString() == "CARD.ASCENDERS_BANE"), "Ethereal curse not exported in exhaust");

            foreach (var state in new[] { before, after, nextTurn, exhausted })
            {
                foreach (var pile in new[] { "draw", "discard", "exhaust" })
                    Check(state.GetProperty(pile + "_pile").GetArrayLength() == state.GetProperty(pile + "_pile_count").GetInt32(), "Pile count mismatch");
                var count = new[] { "hand", "draw_pile", "discard_pile", "exhaust_pile", "play_pile" }
                    .Sum(p => state.GetProperty(p).GetArrayLength());
                Check(count == player.Deck.Cards.Count, "Starter combat card conservation");
            }
            File.WriteAllText(Path.Combine(sandbox, "observations.json"), Json(new { before, after, beforeTurn, nextTurn, exhausted }).GetRawText());
            var result = new { status = "passed", runtime = sim.RuntimeIdentity(),
                checks = new[] { "nunchaku_9_to_0_energy_refund", "pen_nib_9_to_0_double_damage", "happy_flower_2_to_0_energy", "unknown_rule_is_null", "repeat_observation_no_mutation", "draw_order_invariance_modified_duplicates", "discard_movement", "ethereal_exhaust_movement", "pile_count_conservation" } };
            File.WriteAllText(Path.Combine(sandbox, "result.json"), Json(result).GetRawText());
            Console.WriteLine(Json(result));
            Console.WriteLine("Artifacts: " + sandbox);
        }
        finally { sim.CleanUp(); }
    }
}
