// Opt-in training controls. These commands are NEVER policy actions.
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Rngs;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Rooms;

namespace Sts2Headless;

public partial class RunSimulator
{
    private IDisposable? _headlessSelectorScope;
    private void OnHeadlessTurn(CombatState state) => _turnStarted.Set();
    private void OnHeadlessCombatEnd(CombatRoom room) => _combatEnded.Set();

    public void AddTrainingDecisionDetails(Dictionary<string, object?> result)
    {
        if (_runState == null || result.GetValueOrDefault("type") as string == "error") return;
        result["in_combat"] = CombatManager.Instance.IsInProgress;
        if (result.GetValueOrDefault("decision") as string == "card_select")
        {
            result["prompt"] = _cardSelector.PendingPrompt;
            if (CombatManager.Instance.IsInProgress)
                result["combat_state"] = CombatPlayState(_runState.Players[0]);
        }
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
        foreach (var action in request.GetProperty("history").EnumerateArray())
        {
            if (result.GetValueOrDefault("type") as string == "error") return result;
            var arguments = new Dictionary<string, object?>();
            foreach (var p in action.GetProperty("args").EnumerateObject())
                arguments[p.Name] = p.Value.ValueKind == JsonValueKind.Number
                    ? p.Value.GetInt32() : p.Value.GetString();
            result = ExecuteAction(action.GetProperty("action").GetString()!, arguments);
        }
        return result;
    }

    public Dictionary<string, object?> TrainingSample(ulong sampleSeed)
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
        if (cards.Any(c => !admitted.Contains(c.Id.Entry) || c.Enchantment != null || c.Affliction != null)
            || player.Relics.Any(r => r.Id.Entry != "RING_OF_THE_SNAKE")
            || player.Potions.Any() || combat.Enemies.Any(e => e.Monster?.Id.Entry != "SHRINKER_BEETLE"))
            return Error("Root outside qualified starter-beetle sampler; no teacher label emitted");

        // This starter deck cannot reveal or set draw order. The beetle's audited
        // move cycle is deterministic. Retain its current visible intent/history.
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
        return DetectDecisionPoint();
    }
}
