using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Models.Monsters;
using MegaCrit.Sts2.Core.Models.Powers;

// Loaded only in a second, command-only replay. The online policy has exited.
public static class StartupHook
{
    public static void Initialize()
    {
        if (Environment.GetEnvironmentVariable("KAISER_ATTACK_RECEIPT") is not { } path)
            return;
        var lib = Environment.GetEnvironmentVariable("STS2_LIB")!;
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var file = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(file) ? context.LoadFromAssemblyPath(file) : null;
        };
        Install(path);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void Install(string path) => Attacks.Observe(path);
}

internal static class Attacks
{
    private static string path = "";

    internal static void Observe(string destination)
    {
        path = destination;
        var observer = new Harmony("sts2ml.kaiser-executed-attacks");
        foreach (var move in new[] { "PrecisionBeamMove", "LaserMove" })
            observer.Patch(AccessTools.Method(typeof(Rocket), move),
                prefix: new HarmonyMethod(typeof(Attacks), nameof(Record)));
        File.WriteAllText(path, "");
    }

    private static void Record(Rocket __instance, MethodBase __originalMethod)
    {
        var creature = __instance.Creature;
        var combat = creature.CombatState!;
        var player = combat.Players.Single().Creature;
        var side = player.GetPower<SurroundedPower>()?.Facing.ToString();
        var receipt = new {
            round = combat.RoundNumber,
            move = __originalMethod.Name,
            facing = side,
            weak = creature.GetPowerAmount<WeakPower>() > 0,
        };
        File.AppendAllText(path, JsonSerializer.Serialize(receipt) + "\n");
    }
}
