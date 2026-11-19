using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Runs;
using Sts2Headless;

class Program
{
    static int Main(string[] args)
    {
        var root = Path.GetFullPath(args[0]);
        var lib = Path.Combine(root, "artifacts/upstreams/sts2-cli/lib");
        Environment.SetEnvironmentVariable("STS2_LIB", lib);
        Environment.SetEnvironmentVariable("STS2_GAME_DIR", lib);
        AssemblyLoadContext.Default.Resolving += (context, name) => {
            var path = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        };
        var sandbox = Path.Combine(root, "artifacts/headless/event-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(sandbox);
        Directory.SetCurrentDirectory(sandbox);
        Environment.SetEnvironmentVariable("APPDATA", sandbox);
        Environment.SetEnvironmentVariable("LOCALAPPDATA", sandbox);
        foreach (var key in new[] { "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME" })
            Environment.SetEnvironmentVariable(key, sandbox);
        try { Run(sandbox); return 0; }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }

    static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Run(string sandbox)
    {
        Check(typeof(RunSimulator).Assembly.GetType("Sts2Headless.PresentationFix") != null, "Build the current patched host first");
        var observations = new List<object>();
        for (int option = 0; option < 2; option++)
        {
            var sim = new RunSimulator();
            try
            {
                sim.StartRun("Silent", 10, "JUNGLEEVENTQUALIFY001", "en");
                var before = Json(sim.EnterRoom("event", null, "JUNGLE_MAZE_ADVENTURE"));
                Check(before.GetProperty("decision").GetString() == "event_choice", before.ToString());
                var vars = before.GetProperty("options")[option].GetProperty("vars");
                var gold = before.GetProperty("player").GetProperty("gold").GetInt32();
                var hp = before.GetProperty("player").GetProperty("hp").GetInt32();
                var after = Json(sim.ExecuteAction("choose_option", new() { ["option_index"] = option }));
                Check(after.GetProperty("type").GetString() != "error", after.ToString());
                Check(after.GetProperty("player").GetProperty("gold").GetInt32() == gold + vars.GetProperty(option == 0 ? "SoloGold" : "JoinForcesGold").GetInt32(), "Native event gold effect mismatch");
                Check(after.GetProperty("player").GetProperty("hp").GetInt32() == hp - (option == 0 ? vars.GetProperty("SoloHp").GetInt32() : 0), "Native event HP effect mismatch");
                observations.Add(new { option, before, after });
            }
            finally { sim.CleanUp(); }
        }
        var dense = new RunSimulator();
        try
        {
            dense.StartRun("Silent", 10, "DENSEEVENTQUALIFY001", "en");
            dense.SetPlayer(new() { ["hp"] = Json(20) });
            var before = Json(dense.EnterRoom("event", null, "DENSE_VEGETATION"));
            var option = before.GetProperty("options").EnumerateArray().Single(o => o.GetProperty("text_key").GetString()!.EndsWith(".REST"));
            var heal = option.GetProperty("vars").GetProperty("Heal").GetInt32();
            var after = Json(dense.ExecuteAction("choose_option", new() { ["option_index"] = option.GetProperty("index").GetInt32() }));
            Check(after.GetProperty("type").GetString() != "error", after.ToString());
            Check(after.GetProperty("player").GetProperty("hp").GetInt32() == 20 + heal, "Native Dense Vegetation heal mismatch");
            Check(after.GetProperty("options")[0].GetProperty("text_key").GetString()!.EndsWith(".FIGHT"), "Rest must still require the event fight");
            var fight = Json(dense.ExecuteAction("choose_option", new() { ["option_index"] = 0 }));
            Check(fight.GetProperty("decision").GetString() == "combat_play", "Rest must enter the native fight");
            observations.Add(new { event_name = "DenseVegetation", before, after, fight });
        }
        finally { dense.CleanUp(); }
        VerifyDoubleBoss(observations);
        File.WriteAllText(Path.Combine(sandbox, "observations.json"), Json(observations).GetRawText());
        var result = new { passed = true, jungle_options = 2, native_gold_and_hp_verified = true,
            dense_native_heal_and_fight_verified = true, double_boss_verified = true };
        File.WriteAllText(Path.Combine(sandbox, "result.json"), Json(result).GetRawText());
        Console.WriteLine(Json(result));
        Console.WriteLine("Artifacts: " + sandbox);
    }

    // Fixture-only shortcuts reach both real final-act fights quickly. This
    // checks simulator transitions and never supplies a training or win label.
    static void VerifyDoubleBoss(List<object> observations)
    {
        var sim = new RunSimulator();
        try
        {
            sim.StartRun("Silent", 10, "DOUBLEBOSSQUALIFY001", "en");
            RunManager.Instance.EnterAct(2, false).GetAwaiter().GetResult();
            var state = RunManager.Instance.DebugOnlyGetState()!;
            RunManager.Instance.GenerateMap().GetAwaiter().GetResult();
            var map = state.Map!;
            var bosses = new[] { map.BossMapPoint, map.SecondBossMapPoint! };
            Check(bosses[1] != null && bosses[0].coord != bosses[1].coord, "Expected two distinct native A10 boss points");
            for (int i = 0; i < bosses.Length; i++)
            {
                var coord = bosses[i].coord;
                var combat = Json(sim.ExecuteAction("select_map_node", new() { ["col"] = (int)coord.col, ["row"] = (int)coord.row }));
                Check(combat.GetProperty("decision").GetString() == "combat_play", combat.ToString());
                if (i == 0)
                {
                    var post = typeof(RunSimulator).GetMethod("DetectPostCombatState", BindingFlags.Instance | BindingFlags.NonPublic)!;
                    var rejected = Json(post.Invoke(sim, new object[] { state.Players[0], state.CurrentRoom! })!);
                    Check(rejected.GetProperty("type").GetString() == "error", "An unfinished combat must never produce rewards");
                }
                var enemies = CombatManager.Instance.DebugOnlyGetState()!.Enemies.ToArray();
                Check(enemies.Length > 0, "A native boss fight must begin with enemies: " + combat);
                // Some bosses postpone defeat until another turn or phase.
                for (int phase = 0; phase < 8 && CombatManager.Instance.IsInProgress; phase++)
                {
                    enemies = CombatManager.Instance.DebugOnlyGetState()!.Enemies.ToArray();
                    if (enemies.Length != 0)
                        CreatureCmd.Kill(enemies, true).GetAwaiter().GetResult();
                    CombatManager.Instance.CheckWinCondition().GetAwaiter().GetResult();
                    if (CombatManager.Instance.IsInProgress)
                        sim.ExecuteAction("end_turn", new());
                }
                var after = Json(sim.ExecuteAction("proceed", new()));
                if (i == 0)
                {
                    Check(after.GetProperty("decision").GetString() == "map_select", after.ToString());
                    Check(after.GetProperty("choices").EnumerateArray().Any(p =>
                        p.GetProperty("row").GetInt32() == bosses[1].coord.row && p.GetProperty("col").GetInt32() == bosses[1].coord.col),
                        "First boss must lead to a legal second boss choice");
                }
                else Check(after.GetProperty("decision").GetString() == "game_over" && after.GetProperty("victory").GetBoolean(), after.ToString());
                observations.Add(new { boss = i + 1, combat, after });
            }
        }
        finally { sim.CleanUp(); }
    }
}
