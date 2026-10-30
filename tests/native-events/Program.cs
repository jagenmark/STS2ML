using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
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
        File.WriteAllText(Path.Combine(sandbox, "observations.json"), Json(observations).GetRawText());
        var result = new { passed = true, jungle_options = 2, native_gold_and_hp_verified = true,
            dense_native_heal_and_fight_verified = true, suppressed = "Inspected event audio and screen shake only" };
        File.WriteAllText(Path.Combine(sandbox, "result.json"), Json(result).GetRawText());
        Console.WriteLine(Json(result));
        Console.WriteLine("Artifacts: " + sandbox);
    }
}
