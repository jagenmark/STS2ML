using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Hooks;

public static class StartupHook
{
    public static void Initialize()
    {
        if (Environment.GetEnvironmentVariable("STS2_AUTOPSY_RECEIPTS") is not { } path) return;
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var file = Path.Combine(Environment.GetEnvironmentVariable("STS2_LIB")!, name.Name + ".dll");
            return File.Exists(file) ? context.LoadFromAssemblyPath(file) : null;
        };
        Install(path);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void Install(string path) => Observer.Install(path);
}

internal static class Observer
{
    private static string path = "";
    private static int step = -1;
    private static void Begin() => step++;
    private static void Write(object value) =>
        File.AppendAllText(path, JsonSerializer.Serialize(value) + "\n");

    internal static void Install(string file)
    {
        path = file;
        var harmony = new Harmony("sts2ml.lategame.observer");
        var simulator = Assembly.GetEntryAssembly()!.GetType("Sts2Headless.RunSimulator", true)!;
        void Observe(Type type, string method, string prefix) =>
            harmony.Patch(AccessTools.Method(type, method), prefix: new HarmonyMethod(typeof(Observer), prefix));
        Observe(simulator, "ExecuteAction", nameof(Begin));
        Observe(typeof(Hook), "BeforeDeath", nameof(Dying));
        var history = typeof(MegaCrit.Sts2.Core.Combat.History.CombatHistory);
        Observe(history, "DamageReceived", nameof(Damage));
        Write(new { ready = true });
    }

    private static void Damage(Creature receiver, DamageResult result) =>
        Write(new { step, target = receiver.Monster?.Id.Entry ?? "PLAYER", result.UnblockedDamage,
                    result.OverkillDamage, result.BlockedDamage });

    private static void Dying(ICombatState? combatState, Creature creature)
    {
        if (combatState == null || creature.Player == null) return;
        Write(new { step, round = combatState.RoundNumber,
            enemies = combatState.Enemies.Where(e => e.Monster != null)
                .Select(e => new { id = e.Monster!.Id.Entry, hp = e.CurrentHp, max_hp = e.MaxHp }) });
    }
}
