// Adapt display-dependent calls while preserving native effects and rewards.
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using MegaCrit.Sts2.Core.Audio.Debug;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Models.Monsters;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Audio;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.Vfx.Utilities;

namespace Sts2Headless;

public static class PresentationFix
{
    private static bool _installed;
    public static void Install()
    {
        if (_installed) return;
        var harmony = new Harmony("sts2ml.headless.event-presentation");
        foreach (var (model, method) in new[] {
            (typeof(JungleMazeAdventure), "SafetyInNumbers"), (typeof(DenseVegetation), "Rest"),
            (typeof(Amalgamator), "CombineDefends"), (typeof(Amalgamator), "CombineStrikes") })
        {
            var stateMachine = model.GetNestedTypes(BindingFlags.NonPublic).Single(t => t.Name.StartsWith("<" + method + ">"));
            var moveNext = stateMachine.GetMethod("MoveNext", BindingFlags.Instance | BindingFlags.NonPublic)!;
            harmony.Patch(moveNext, transpiler: new HarmonyMethod(typeof(PresentationFix), nameof(RemovePresentation)));
        }
        harmony.Patch(AccessTools.Method(typeof(NCrystalSphereScreen), "ShowScreen"),
            prefix: new HarmonyMethod(typeof(PresentationFix), nameof(PlayCrystalSphere)));
        foreach (var arm in new[] { typeof(Crusher), typeof(Rocket) })
            harmony.Patch(AccessTools.Method(arm, "BeforeDeath"),
                transpiler: new HarmonyMethod(typeof(PresentationFix), nameof(ReplaceArmDeathSound)));
        _installed = true;
    }

    private static void PlayDeathSoundIfAvailable(NAudioManager? audio, string path, float volume)
        => audio?.PlayOneShot(path, volume);

    private static IEnumerable<CodeInstruction> ReplaceArmDeathSound(IEnumerable<CodeInstruction> instructions)
    {
        var replaced = 0;
        foreach (var instruction in instructions)
        {
            if (instruction.opcode == OpCodes.Callvirt && instruction.operand is MethodInfo method
                && method.DeclaringType == typeof(NAudioManager) && method.Name == "PlayOneShot"
                && method.GetParameters().Select(p => p.ParameterType).SequenceEqual(new[] { typeof(string), typeof(float) }))
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = AccessTools.Method(typeof(PresentationFix), nameof(PlayDeathSoundIfAvailable));
                replaced++;
            }
            yield return instruction;
        }
        if (replaced != 1) throw new InvalidOperationException("Unexpected boss arm death audio call count");
    }

    // The game's PlayMinigame discards the screen handle and awaits the last
    // click. Use the native click action with a fixed, visible-fog-only policy.
    // Completion, rewards, bad items and the event's payment stay in the game.
    private static bool PlayCrystalSphere(CrystalSphereMinigame __0)
    {
        var game = __0;
        var size = game.GridSize;
        var cells = game.cells.Cast<CrystalSphereCell>()
            .OrderBy(c => Math.Abs(2 * c.X + 1 - size.X) + Math.Abs(2 * c.Y + 1 - size.Y))
            .ThenBy(c => c.Y).ThenBy(c => c.X).ToArray();
        while (!game.IsFinished)
        {
            var before = game.DivinationCount;
            var cell = cells.First(c => c.IsHidden);
            game.CellClicked(cell).GetAwaiter().GetResult();
            if (game.DivinationCount != before - 1)
                throw new InvalidOperationException("Crystal Sphere did not consume exactly one divination");
        }
        return false;
    }

    private static int SkipDebugAudio(NDebugAudioManager? manager, string path, float volume, PitchVariance pitch) => 0;
    private static void SkipStopAudio(NDebugAudioManager? manager, int handle, float fade) { }
    private static void SkipRumble(NGame? game, ShakeStrength strength, ShakeDuration duration, RumbleStyle style) { }
    private static void SkipShake(NGame? game, ShakeStrength strength) { }

    private static IEnumerable<CodeInstruction> RemovePresentation(IEnumerable<CodeInstruction> instructions, MethodBase __originalMethod)
    {
        var plays = 0;
        var stops = 0;
        var rumbles = 0;
        var shakes = 0;
        foreach (var instruction in instructions)
        {
            string? replacement = null;
            if (instruction.opcode == OpCodes.Callvirt && instruction.operand is MethodInfo method)
            {
                if (method.DeclaringType == typeof(NDebugAudioManager) && method.Name == "Play")
                { replacement = nameof(SkipDebugAudio); plays++; }
                else if (method.DeclaringType == typeof(NDebugAudioManager) && method.Name == "Stop")
                { replacement = nameof(SkipStopAudio); stops++; }
                else if (method.DeclaringType == typeof(NGame) && method.Name == "ScreenRumble")
                { replacement = nameof(SkipRumble); rumbles++; }
                else if (method.DeclaringType == typeof(NGame) && method.Name == "ScreenShakeTrauma")
                { replacement = nameof(SkipShake); shakes++; }
            }
            if (replacement != null)
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = typeof(PresentationFix).GetMethod(replacement, BindingFlags.Static | BindingFlags.NonPublic)!;
            }
            yield return instruction;
        }
        var model = __originalMethod.DeclaringType?.DeclaringType;
        var dense = model == typeof(DenseVegetation);
        var combinesCards = model == typeof(Amalgamator);
        if (plays != (combinesCards ? 0 : dense ? 2 : 1) || stops != (dense ? 1 : 0)
            || rumbles != (dense ? 1 : 0) || shakes != (combinesCards ? 2 : 0))
            throw new InvalidOperationException("Unexpected pinned event presentation calls; refusing partial patch");
    }
}
