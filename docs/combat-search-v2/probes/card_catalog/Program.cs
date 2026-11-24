using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;
using MegaCrit.Sts2.Core.Models;
using Sts2Headless;

// Offline static export. Only canonical models and one ordinary upgrade are read.
class Program
{
    static void Main(string[] args)
    {
        var lib = Path.GetFullPath(args[0]);
        Environment.SetEnvironmentVariable("STS2_LIB", lib);
        Environment.SetEnvironmentVariable("STS2_GAME_DIR", lib);
        AssemblyLoadContext.Default.Resolving += (ctx, name) => {
            var file = Path.Combine(lib, name.Name + ".dll");
            return File.Exists(file) ? ctx.LoadFromAssemblyPath(file) : null;
        };
        Export(args[1], args[2]);
    }

    static object Variant(CardModel card) => new {
        cost = card.EnergyCost.GetResolved(), card_type = card.Type.ToString(),
        target_type = card.TargetType.ToString(), costs_x = card.EnergyCost.CostsX,
        star_cost = card.CurrentStarCost, stars_x = card.HasStarCostX,
        multiplayer_only = card.MultiplayerConstraint.ToString() == "MultiplayerOnly",
        keywords = card.Keywords.Select(k => k.ToString()).Order(),
        stats = card.DynamicVars.Values.ToDictionary(v => v.Name.ToLowerInvariant(), v => v.BaseValue)
    };

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Export(string localization, string destination)
    {
        var sim = new RunSimulator();
        sim.StartRun("Silent", 10, "CSV9FIX_CATALOG", "en");
        var strings = JsonSerializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(localization))!;
        var output = new SortedDictionary<string,object>();
        foreach (var model in ModelDb.AllCards)
        {
            var card = model.ToMutable();
            var variants = new List<JsonElement> { JsonSerializer.SerializeToElement(Variant(card)) };
            if (card.IsUpgradable) {
                card.UpgradeInternal();
                card.FinalizeUpgradeInternal();
                variants.Add(JsonSerializer.SerializeToElement(Variant(card)));
            }
            var id = model.Id.Entry;
            output.Add(id, new { name = strings.GetValueOrDefault(id + ".title",id),
                description = strings.GetValueOrDefault(id + ".description",""), variants });
        }
        File.WriteAllText(destination, JsonSerializer.Serialize(output));
        sim.CleanUp();
    }
}
