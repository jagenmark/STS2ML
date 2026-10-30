// Keep native event gameplay; remove one unguarded debug-audio call only.
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using MegaCrit.Sts2.Core.Audio.Debug;
using MegaCrit.Sts2.Core.Models.Events;

namespace Sts2Headless;

public static class PresentationFix
{
    private static bool _installed;
    public static void Install()
    {
        if (_installed) return;
        var stateMachine = typeof(JungleMazeAdventure).GetNestedTypes(BindingFlags.NonPublic)
            .Single(t => t.Name.StartsWith("<SafetyInNumbers>"));
        var moveNext = stateMachine.GetMethod("MoveNext", BindingFlags.Instance | BindingFlags.NonPublic)!;
        new Harmony("sts2ml.headless.jungle-audio").Patch(moveNext,
            transpiler: new HarmonyMethod(typeof(PresentationFix), nameof(RemoveDebugAudio)));
        _installed = true;
    }

    private static int SkipDebugAudio(NDebugAudioManager? manager, string path, float volume, PitchVariance pitch) => 0;

    private static IEnumerable<CodeInstruction> RemoveDebugAudio(IEnumerable<CodeInstruction> instructions)
    {
        var calls = 0;
        foreach (var instruction in instructions)
        {
            if (instruction.opcode == OpCodes.Callvirt && instruction.operand is MethodInfo method
                && method.DeclaringType == typeof(NDebugAudioManager) && method.Name == "Play")
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = typeof(PresentationFix).GetMethod(nameof(SkipDebugAudio), BindingFlags.Static | BindingFlags.NonPublic)!;
                calls++;
            }
            yield return instruction;
        }
        if (calls != 1) throw new InvalidOperationException("Unexpected pinned Jungle Maze audio method; refusing partial patch");
    }
}
