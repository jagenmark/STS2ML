using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;

public static class StartupHook
{
    public static void Initialize()
    {
        if (Environment.GetEnvironmentVariable("STS2_COMBAT_V2_RECEIPTS") is not { } path)
            return;
        var lib = Environment.GetEnvironmentVariable("STS2_LIB")!;
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var dependency = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(dependency) ? context.LoadFromAssemblyPath(dependency) : null;
        };
        Install(path);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void Install(string path) => CombatV2Observer.Install(path);
}

internal static class CombatV2Observer
{
    private static string _path = "";
    private static bool _action;
    private static int _step = -1;
    private static object? _draw;
    private static object? _exit;
    private static bool _escaped;
    private static bool _earlyDraw;

    internal static void Install(string path)
    {
        _path = path;
        var simulator = Assembly.GetEntryAssembly()!.GetType("Sts2Headless.RunSimulator", true)!;
        var harmony = new Harmony("sts2ml.combat-v2-observer");
        harmony.Patch(AccessTools.Method(simulator, "ExecuteAction"),
            prefix: Patch(nameof(Begin)), postfix: Patch(nameof(Finish)));
        harmony.Patch(AccessTools.Method(typeof(CardPileCmd), "DrawInternal"), prefix: Patch(nameof(BeforeDraw)));
        harmony.Patch(AccessTools.Method(simulator, "DetectPostCombatState"), prefix: Patch(nameof(BeforeRewards)));
        harmony.Patch(AccessTools.Method(typeof(Hook), "AfterCombatEnd"), prefix: Patch(nameof(CombatEnded)));
        File.WriteAllText(_path, "{}\n");
    }

    private static HarmonyMethod Patch(string name) => new(typeof(CombatV2Observer), name);

    private static void Begin()
    {
        _action = true;
        _step++;
        _draw = _exit = null;
        _escaped = _earlyDraw = false;
    }

    private static void Finish()
    {
        _action = false;
        if (_draw != null || _exit != null)
            File.AppendAllText(_path, JsonSerializer.Serialize(new { step = _step, draw = _draw, exit = _exit }) + "\n");
    }

    private static object[] Powers(Creature creature) =>
        creature.Powers.OrderBy(power => power.Id.Entry, StringComparer.Ordinal)
            .Select(power => (object)new { id = power.Id.ToString(), amount = power.Amount }).ToArray();

    private static object CreatureBoard(Creature creature) =>
        new { hp = creature.CurrentHp, max_hp = creature.MaxHp, block = creature.Block, powers = Powers(creature) };

    private static object[] Cards(IEnumerable<CardModel> cards) =>
        cards.GroupBy(card => (id: card.Id.ToString(), type: card.Type.ToString(), upgrades: card.CurrentUpgradeLevel))
            .OrderBy(group => group.Key.id, StringComparer.Ordinal)
            .ThenBy(group => group.Key.type, StringComparer.Ordinal)
            .ThenBy(group => group.Key.upgrades)
            .Select(group => (object)new { group.Key.id, group.Key.type, group.Key.upgrades, count = group.Count() })
            .ToArray();

    private static void BeforeDraw(Player player, bool fromHandDraw)
    {
        if (!_action || _draw != null || player.PlayerCombatState is not { } pcs
            || player.Creature.CombatState is not { } combat)
            return;
        if (!fromHandDraw)
        {
            _earlyDraw = true;
            return;
        }
        if (_earlyDraw)
        {
            _draw = new { early_draw = true };
            return;
        }
        _draw = new {
            early_draw = false,
            round = combat.RoundNumber,
            player = CreatureBoard(player.Creature),
            max_energy = pcs.MaxEnergy,
            enemies = combat.Enemies.Where(enemy => enemy.CurrentHp > 0 && enemy.Monster != null)
                .Select(enemy => new { id = enemy.Monster!.Id.ToString(), board = CreatureBoard(enemy) }).ToArray(),
            live = Cards(pcs.Hand.Cards.Concat(pcs.DrawPile.Cards).Concat(pcs.DiscardPile.Cards)),
            retained = Cards(pcs.Hand.Cards),
            draw_count = pcs.DrawPile.Cards.Count,
            discard_count = pcs.DiscardPile.Cards.Count,
            exhaust_count = pcs.ExhaustPile.Cards.Count,
        };
    }

    private static void BeforeRewards(Player player)
    {
        if (_action && !_escaped)
            RecordExit(player, false);
    }

    private static void CombatEnded(ICombatState combatState)
    {
        if (_action && combatState.Players.Count == 1)
            RecordExit(combatState.Players[0], combatState.EscapedCreatures.Contains(combatState.Players[0].Creature));
    }

    private static void RecordExit(Player player, bool escaped)
    {
        _escaped = escaped;
        _exit = new { hp = player.Creature.CurrentHp, max_hp = player.Creature.MaxHp, escaped };
    }
}
