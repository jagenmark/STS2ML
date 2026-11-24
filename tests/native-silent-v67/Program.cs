using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models.Powers;
using Sts2Headless;

// The public scenario protocol cannot grant player Artifact. Use its native command
// only for fixture setup, then play and observe through the pinned RunSimulator.
class Program
{
    static void Main(string[] args)
    {
        var lib = Environment.GetEnvironmentVariable("STS2_LIB")!;
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var path = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        };
        Run(args[0] == "after");
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Run(bool afterPlay)
    {
        var sim = new RunSimulator();
        try
        {
            sim.StartRun("Silent", 10, "CSV12FIX_ARTIFACT_WRAITH", "en");
            sim.SetPlayer(new() { ["deck"] = JsonSerializer.SerializeToElement(new[] { "WRAITH_FORM" }) });
            sim.EnterRoom("monster", "WATERFALL_GIANT_BOSS", null);
            var player = CombatManager.Instance.DebugOnlyGetState()!.Players.Single().Creature;
            var args = new Dictionary<string, object?> { ["card_index"] = 0 };
            if (afterPlay) sim.ExecuteAction("play_card", args);
            PowerCmd.Apply<ArtifactPower>(new ThrowingPlayerChoiceContext(), player, 1, player, null).GetAwaiter().GetResult();
            var before = typeof(RunSimulator).GetMethod("DetectDecisionPoint", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(sim, null);
            var after = afterPlay ? sim.ExecuteAction("end_turn", new()) : sim.ExecuteAction("play_card", args);
            Console.WriteLine(JsonSerializer.Serialize(new { before, after }));
        }
        finally { sim.CleanUp(); }
    }
}
