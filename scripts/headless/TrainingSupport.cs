// Opt-in training controls. These commands are NEVER policy actions.
using System.Text.Json;
using System.Reflection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Rngs;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Rooms;

namespace Sts2Headless;

public partial class RunSimulator
{
    private IDisposable? _headlessSelectorScope;
    private object? _historyCombat;
    private readonly List<Dictionary<string, object?>> _publicCombatHistory = new();
    private readonly HashSet<string> _drawKnowledgeRisks = new();
    private Dictionary<string, object?> _publicSelectionSource = new();
    // These effects can establish remembered draw order. Until a public belief
    // tracker supports them, retain the full run but do not label its affected fight.
    private static readonly HashSet<string> DrawKnowledgeModels = new() {
        "CASCADE", "COSMIC_INDIFFERENCE", "GLIMMER", "HAVOC", "HEADBUTT",
        "I_AM_INVINCIBLE", "MAYHEM", "NOSTALGIA", "PHOTON_CUT", "REBOUND",
        "SHINING_STRIKE", "THINKING_AHEAD", "DISTILLED_CHAOS", "MAYHEM_POWER",
        "NOSTALGIA_POWER", "REBOUND_POWER"
    };
    private void OnHeadlessTurn(CombatState state) => _turnStarted.Set();
    private void OnHeadlessCombatEnd(CombatRoom room) => _combatEnded.Set();

    public void AddTrainingDecisionDetails(Dictionary<string, object?> result)
    {
        if (_runState == null || result.GetValueOrDefault("type") as string == "error") return;
        result["in_combat"] = CombatManager.Instance.IsInProgress;
        if (result.GetValueOrDefault("decision") as string is "card_select" or "card_reward" or "bundle_select")
        {
            result["prompt"] = _cardSelector.PendingPrompt;
            result["selection_source"] = new Dictionary<string, object?>(_publicSelectionSource);
            if (CombatManager.Instance.IsInProgress)
                result["combat_state"] = CombatPlayState(_runState.Players[0]);
        }
        if (CombatManager.Instance.IsInProgress)
        {
            var combat = CombatManager.Instance.DebugOnlyGetState();
            if (!ReferenceEquals(_historyCombat, combat))
            {
                _historyCombat = combat;
                _publicCombatHistory.Clear();
                _drawKnowledgeRisks.Clear();
            }
            var player = _runState.Players[0];
            var pcs = player.PlayerCombatState!;
            var cards = player.Deck.Cards.Concat(pcs.Hand.Cards).Concat(pcs.DrawPile.Cards)
                .Concat(pcs.DiscardPile.Cards).Concat(pcs.ExhaustPile.Cards).Concat(pcs.PlayPile.Cards);
            var models = cards.Select(c => c.Id.Entry).Concat(player.Relics.Select(r => r.Id.Entry))
                .Concat(player.Potions.Select(p => p.Id.Entry)).Concat(player.Creature.Powers.Select(p => p.Id.Entry));
            foreach (var entry in models.Where(DrawKnowledgeModels.Contains)) _drawKnowledgeRisks.Add(entry);
            var view = result.GetValueOrDefault("decision") as string == "combat_play" ? result
                : result.GetValueOrDefault("combat_state") as Dictionary<string, object?>;
            if (view != null && _publicCombatHistory.Count < 64
                && (_publicCombatHistory.Count == 0 || !Equals(_publicCombatHistory[^1]["round"], view["round"])))
                _publicCombatHistory.Add(new() { ["round"] = view["round"], ["enemies"] = view["enemies"] });
            result["public_combat_history"] = _publicCombatHistory.ToList();
            result["act1_search_support"] = new Dictionary<string, object?> {
                ["supported"] = _drawKnowledgeRisks.Count == 0 && _publicCombatHistory.Count < 64,
                ["draw_knowledge_risks"] = _drawKnowledgeRisks.OrderBy(s => s).ToList(),
                ["profile"] = "silent-a10-act1-mc-v2",
            };
        }
    }

    private void RememberPublicAction(string action, Dictionary<string, object?>? args)
    {
        if (_runState == null) return;
        var player = _runState.Players[0];
        if (action == "play_card" && args?.TryGetValue("card_index", out var ci) == true)
        {
            var index = Convert.ToInt32(ci);
            var hand = player.PlayerCombatState?.Hand.Cards;
            if (hand != null && index >= 0 && index < hand.Count)
                _publicSelectionSource = new() { ["kind"] = action, ["id"] = hand[index].Id.ToString() };
        }
        else if (action == "use_potion" && args?.TryGetValue("potion_index", out var pi) == true)
        {
            var potion = player.Potions.ElementAtOrDefault(Convert.ToInt32(pi));
            if (potion != null) _publicSelectionSource = new() { ["kind"] = action, ["id"] = potion.Id.ToString() };
        }
        else if (action == "end_turn") _publicSelectionSource = new() { ["kind"] = action };
    }

    public Dictionary<string, object?> TrainingRestore(JsonElement request)
    {
        var result = StartRun("Silent", 10, request.GetProperty("seed").GetString(), "en");
        if (result.GetValueOrDefault("type") as string == "error") return result;
        if (request.TryGetProperty("encounter", out var encounter))
        {
            // First curriculum: native Act 1 beetle, original starter deck/relic.
            if (encounter.GetString() != "SHRINKER_BEETLE_WEAK")
                return Error("Encounter not qualified for starter curriculum");
            if (request.TryGetProperty("hp", out var hp))
            {
                if (hp.GetInt32() < 1 || hp.GetInt32() > 70) return Error("Invalid curriculum HP");
                result = SetPlayer(new() { ["hp"] = hp });
                if (result.GetValueOrDefault("type") as string == "error") return result;
            }
            result = EnterRoom("monster", encounter.GetString(), null);
        }
        AddTrainingDecisionDetails(result);
        foreach (var action in request.GetProperty("history").EnumerateArray())
        {
            if (result.GetValueOrDefault("type") as string == "error") return result;
            var arguments = new Dictionary<string, object?>();
            foreach (var p in action.GetProperty("args").EnumerateObject())
                arguments[p.Name] = p.Value.ValueKind == JsonValueKind.Number
                    ? p.Value.GetInt32() : p.Value.GetString();
            result = ExecuteAction(action.GetProperty("action").GetString()!, arguments);
            AddTrainingDecisionDetails(result);
        }
        return result;
    }

    public Dictionary<string, object?> TrainingSample(ulong sampleSeed, string profile = "silent-a10-starter-beetle-v1")
    {
        if (_runState == null || (!IsPlayPhase() && !_cardSelector.HasPending))
            return Error("Sampling requires a stable combat decision root");
        var player = _runState.Players[0];
        var pcs = player.PlayerCombatState!;
        var combat = CombatManager.Instance.DebugOnlyGetState()!;
        var admitted = new HashSet<string> {
            "STRIKE_SILENT", "DEFEND_SILENT", "NEUTRALIZE", "SURVIVOR", "ASCENDERS_BANE"
        };
        var cards = player.Deck.Cards.Concat(pcs.Hand.Cards).Concat(pcs.DrawPile.Cards)
            .Concat(pcs.DiscardPile.Cards).Concat(pcs.ExhaustPile.Cards).Concat(pcs.PlayPile.Cards);
        if (profile == "silent-a10-starter-beetle-v1" && (cards.Any(c => !admitted.Contains(c.Id.Entry) || c.Enchantment != null || c.Affliction != null)
            || player.Relics.Any(r => r.Id.Entry != "RING_OF_THE_SNAKE")
            || player.Potions.Any() || combat.Enemies.Any(e => e.Monster?.Id.Entry != "SHRINKER_BEETLE")))
            return Error("Root outside qualified starter-beetle sampler; no teacher label emitted");
        if (profile != "silent-a10-starter-beetle-v1" && profile != "silent-a10-act1-mc-v2")
            return Error("Unknown sampler profile");
        if (profile == "silent-a10-act1-mc-v2" && (_runState.CurrentActIndex != 0
            || _drawKnowledgeRisks.Count > 0 || _publicCombatHistory.Count >= 64))
            return Error("Unsupported Act 1 draw knowledge/history; no teacher label emitted");

        // Retain current visible intents/history. The broad profile excludes
        // known draw-order effects, but remains an experimental belief sampler.
        // Sort BEFORE shuffling: even finite Monte Carlo samples must not depend
        // on the actual hidden permutation, including upgraded duplicate cards.
        var master = new Rng(sampleSeed);
        var pile = GetBackingList<CardModel>(pcs.DrawPile, "_cards")!;
        var ordered = pile.OrderBy(c => JsonSerializer.Serialize(PublicPile(new[] { c })),
            StringComparer.Ordinal).ToList();
        master.Shuffle(ordered);
        pile.Clear();
        pile.AddRange(ordered);
        // Reset existing objects, rather than replacing them: cached references
        // must also lose the actual run's future random sequence.
        foreach (var kind in Enum.GetValues<RunRngType>())
            _runState.Rng.GetRng(kind).LoadFromSerializable(new Rng(master.NextUnsignedLong()).ToSerializable());
        foreach (var kind in Enum.GetValues<PlayerRngType>())
            player.PlayerRng.GetRng(kind).LoadFromSerializable(new Rng(master.NextUnsignedLong()).ToSerializable());
        if (profile == "silent-a10-act1-mc-v2")
        {
            // Monster-local RNG is separate from RunRngSet.MonsterAi. Preserve
            // current telegraphed intent and state-machine history; replace future rolls.
            foreach (var enemy in combat.Enemies)
                if (enemy.Monster is { } monster)
                    monster.Rng.LoadFromSerializable(new Rng(master.NextUnsignedLong()).ToSerializable());
            // Future encounter spawns may use the encounter's own RNG.
            if (_runState.CurrentRoom is CombatRoom room)
            {
                var encounter = room.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public)
                    .Where(p => typeof(EncounterModel).IsAssignableFrom(p.PropertyType))
                    .Select(p => p.GetValue(room)).OfType<EncounterModel>().FirstOrDefault();
                if (encounter != null && typeof(EncounterModel).GetField("_rng", BindingFlags.Instance | BindingFlags.NonPublic)
                    ?.GetValue(encounter) is Rng rng)
                    rng.LoadFromSerializable(new Rng(master.NextUnsignedLong()).ToSerializable());
            }
            Rng.Chaotic.LoadFromSerializable(new Rng(master.NextUnsignedLong()).ToSerializable());
        }
        return DetectDecisionPoint();
    }
}
