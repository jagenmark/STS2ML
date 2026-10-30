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
        // Allows testing the proposed presentation-only patch while the previous
        // host remains loaded by a long collection job. Updated hosts install it.
        if (typeof(RunSimulator).Assembly.GetType("Sts2Headless.PresentationFix") == null)
            PresentationFix.Install();
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
        File.WriteAllText(Path.Combine(sandbox, "observations.json"), Json(observations).GetRawText());
        var result = new { passed = true, options = 2, native_gold_and_hp_verified = true, suppressed = "Jungle Maze debug audio only" };
        File.WriteAllText(Path.Combine(sandbox, "result.json"), Json(result).GetRawText());
        Console.WriteLine(Json(result));
        Console.WriteLine("Artifacts: " + sandbox);
    }
}
