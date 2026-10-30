// STS2ML extensions for the pinned v0.111.0 engine. Public UI state only.
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;

namespace Sts2Headless;

public partial class RunSimulator
{
    private Dictionary<string, object?> PublicRelic(RelicModel relic)
    {
        // Do not reflect arbitrary saved/private properties: those may contain
        // latent choices. These getters are the game's public relic UI contract.
        var vars = relic.DynamicVars.Values.ToDictionary(v => v.Name, v => (object?)v.BaseValue);
        int? counter = relic.ShowCounter ? relic.DisplayAmount : null;
        return new()
        {
            ["id"] = relic.Id.ToString(),
            ["name"] = _loc.Relic(relic.Id.Entry),
            ["description"] = _loc.Bilingual("relics", relic.Id.Entry + ".description"),
            ["vars"] = vars,
            ["show_counter"] = relic.ShowCounter,
            ["counter"] = counter,
            ["status"] = relic.Status.ToString(),
            ["is_used_up"] = relic.IsUsedUp,
            ["stack_count"] = relic.StackCount,
            ["counter_rule"] = RelicCounterRule(relic, counter),
        };
    }

    private static Dictionary<string, object?>? RelicCounterRule(RelicModel relic, int? counter)
    {
        // Explicit rules qualified against this assembly, never guessed from a
        // generic counter. Unknown relics still expose their actual UI counter.
        int threshold;
        string unit, effect;
        decimal amount;
        switch (relic.Id.Entry)
        {
            case "NUNCHAKU":
                threshold = relic.DynamicVars.Cards.IntValue;
                unit = "attack_played";
                effect = "gain_energy";
                amount = relic.DynamicVars["Energy"].BaseValue;
                break;
            case "HAPPY_FLOWER":
                threshold = relic.DynamicVars["Turns"].IntValue;
                unit = "player_turn_started";
                effect = "gain_energy";
                amount = relic.DynamicVars["Energy"].BaseValue;
                break;
            case "PEN_NIB":
                threshold = 10;
                unit = "attack_played";
                effect = "attack_damage_multiplier";
                amount = 2;
                break;
            default:
                return null;
        }
        // During an activation animation DisplayAmount can equal the threshold.
        // Preserve that display, but do not invent a ready-to-trigger decision.
        int? remaining = counter is >= 0 && counter < threshold && !relic.IsUsedUp
            ? threshold - counter : null;
        return new()
        {
            ["unit"] = unit,
            ["threshold"] = threshold,
            ["remaining"] = remaining,
            ["effect"] = effect,
            ["effect_amount"] = amount,
        };
    }

    private void AddPublicCardDetails(CardModel card, Dictionary<string, object?> result)
    {
        result["upgrades"] = card.CurrentUpgradeLevel;
        result["max_upgrades"] = card.MaxUpgradeLevel;
        result["costs_x"] = card.EnergyCost?.CostsX ?? false;
        result["star_cost"] = card.CurrentStarCost;
        result["stars_x"] = card.HasStarCostX;
        result["exhaust_on_next_play"] = card.ExhaustOnNextPlay;
        result["retain_this_turn"] = card.ShouldRetainThisTurn;
        result["sly_this_turn"] = card.IsSlyThisTurn;
        if (card.Enchantment is { } enchantment)
            result["enchantment_state"] = new Dictionary<string, object?>
            {
                ["id"] = enchantment.Id.ToString(),
                ["amount"] = enchantment.Amount,
                ["show_counter"] = enchantment.ShowAmount,
                ["counter"] = enchantment.ShowAmount ? enchantment.DisplayAmount : (int?)null,
                ["status"] = enchantment.Status.ToString(),
                ["vars"] = enchantment.DynamicVars.Values.ToDictionary(v => v.Name, v => v.BaseValue),
            };
        if (card.Affliction is { } affliction)
            result["affliction_state"] = new Dictionary<string, object?>
            {
                ["id"] = affliction.Id.ToString(),
                ["amount"] = affliction.Amount,
            };
    }

    private List<Dictionary<string, object?>> PublicPile(IEnumerable<CardModel>? cards)
    {
        // Canonical multiset: sort the entire public representation, including
        // modifiers on duplicate cards. No draw order or underlying pile index.
        return (cards ?? Enumerable.Empty<CardModel>()).Select(card =>
        {
            var result = new Dictionary<string, object?>
            {
                ["id"] = card.Id.ToString(),
                ["name"] = _loc.Card(card.Id.Entry),
                ["cost"] = card.EnergyCost?.GetResolved() ?? 0,
                ["type"] = card.Type.ToString(),
                ["rarity"] = card.Rarity.ToString(),
                ["target_type"] = card.TargetType.ToString(),
                ["description"] = _loc.Bilingual("cards", card.Id.Entry + ".description"),
                // Outside-hand base values, explicitly distinguished from the
                // target-sensitive preview already exported for hand cards.
                ["stats"] = card.DynamicVars.Values.ToDictionary(v => v.Name.ToLowerInvariant(), v => v.BaseValue),
                ["stats_mode"] = "base",
                ["keywords"] = card.Keywords.Where(k => k != CardKeyword.None)
                    .Select(k => k.ToString()).OrderBy(k => k, StringComparer.Ordinal).ToList(),
            };
            AddPublicCardDetails(card, result);
            return result;
        }).OrderBy(card => JsonSerializer.Serialize(card), StringComparer.Ordinal).ToList();
    }
}
