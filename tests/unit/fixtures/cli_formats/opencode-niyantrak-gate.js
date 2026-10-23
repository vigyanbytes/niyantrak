// Niyantrak gate for OpenCode. Managed by `niyantrak gate install --cli opencode`;
// remove with `niyantrak gate uninstall --cli opencode`. Marker: gate check --cli opencode
//
// OpenCode loads plugin/*.js from its config dir and calls tool.execute.before before every tool call;
// throwing blocks the call and the message goes back to the model. The decision is made by the same
// Niyantrak gate every other CLI uses. If the gate cannot answer, the call is blocked (fail closed).
import { spawnSync } from "node:child_process";

const GATE = ["niyantrak", "gate", "check", "--cli", "opencode"];

export const NiyantrakGate = async () => ({
  "tool.execute.before": async (input, output) => {
    const payload = JSON.stringify({ tool: input && input.tool, args: (output && output.args) || {} });
    const r = spawnSync(GATE[0], GATE.slice(1), { input: payload, encoding: "utf8", timeout: 15000 });
    let res = null;
    try { res = JSON.parse(r.stdout || ""); } catch (e) { res = null; }
    if (!res || (res.decision !== "allow" && res.decision !== "deny")) {
      throw new Error("Niyantrak gate unavailable (" + (r.error ? r.error.message : "exit " + r.status) +
        "); tool call blocked. Remove the gate with: niyantrak gate uninstall --cli opencode");
    }
    if (res.decision === "deny") throw new Error(res.reason || "Blocked by Niyantrak gate");
  },
});
