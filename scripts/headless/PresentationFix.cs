// Keep native event gameplay; remove inspected audio/screen-shake calls only.
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using MegaCrit.Sts2.Core.Audio.Debug;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Vfx.Utilities;

namespace Sts2Headless;

public static class PresentationFix
{
    private static bool _installed;
    public static void Install()
    {
        if (_installed) return;
        var harmony = new Harmony("sts2ml.headless.event-presentation");
        foreach (var (model, method) in new[] { (typeof(JungleMazeAdventure), "SafetyInNumbers"), (typeof(DenseVegetation), "Rest") })
        {
            var stateMachine = model.GetNestedTypes(BindingFlags.NonPublic).Single(t => t.Name.StartsWith("<" + method + ">"));
            var moveNext = stateMachine.GetMethod("MoveNext", BindingFlags.Instance | BindingFlags.NonPublic)!;
            harmony.Patch(moveNext, transpiler: new HarmonyMethod(typeof(PresentationFix), nameof(RemovePresentation)));
        }
        _installed = true;
    }

    private static int SkipDebugAudio(NDebugAudioManager? manager, string path, float volume, PitchVariance pitch) => 0;
    private static void SkipStopAudio(NDebugAudioManager? manager, int handle, float fade) { }
    private static void SkipRumble(NGame? game, ShakeStrength strength, ShakeDuration duration, RumbleStyle style) { }

    private static IEnumerable<CodeInstruction> RemovePresentation(IEnumerable<CodeInstruction> instructions, MethodBase __originalMethod)
    {
        var plays = 0;
        var stops = 0;
        var rumbles = 0;
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
            }
            if (replacement != null)
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = typeof(PresentationFix).GetMethod(replacement, BindingFlags.Static | BindingFlags.NonPublic)!;
            }
            yield return instruction;
        }
        var dense = __originalMethod.DeclaringType?.DeclaringType == typeof(DenseVegetation);
        if (plays != (dense ? 2 : 1) || stops != (dense ? 1 : 0) || rumbles != (dense ? 1 : 0))
            throw new InvalidOperationException("Unexpected pinned event presentation calls; refusing partial patch");
    }
}
