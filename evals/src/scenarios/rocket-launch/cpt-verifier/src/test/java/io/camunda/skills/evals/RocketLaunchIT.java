package io.camunda.skills.evals;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import io.camunda.client.api.worker.JobWorker;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;

/**
 * Verifier for the rocket-launch scenario.
 *
 * Runs in CPT remote-runtime mode against the orchestration cluster
 * the agent worked against. The test re-deploys the agent's BPMN
 * file from /agent-workspace, registers permissive job workers for
 * the typical task types ("countdown", "liftoff") and any others
 * the agent might have invented, and asserts a process instance
 * reaches the end state.
 *
 * Re-deploying inside the test (rather than relying on the agent's
 * prior deploy persisting) keeps the test hermetic against CPT's
 * between-run data cleanup.
 */
@CamundaProcessTest
class RocketLaunchIT {

  private static final Path AGENT_WORKSPACE = Path.of("/agent-workspace");

  // Injected by CPT extension.
  @SuppressWarnings("unused")
  private CamundaClient client;

  @Test
  void rocketLaunchCompletes() throws Exception {
    Path bpmn = findAgentBpmn();

    client.newDeployResourceCommand().addResourceFile(bpmn.toString()).send().join();

    // Permissive workers that auto-complete any job of these types
    // with empty variables. The agent's BPMN may or may not use
    // these names — registering them is harmless if it doesn't.
    try (JobWorker countdown = openCompletingWorker("countdown");
         JobWorker liftoff = openCompletingWorker("liftoff")) {

      ProcessInstanceEvent instance =
          client
              .newCreateInstanceCommand()
              .bpmnProcessId("RocketLaunch")
              .latestVersion()
              .variables(Map.of("countdownSeconds", 3))
              .send()
              .join();

      CamundaAssert.assertThat(instance).isCompleted();
    }
  }

  private JobWorker openCompletingWorker(String jobType) {
    return client
        .newWorker()
        .jobType(jobType)
        .handler((jobClient, job) -> jobClient.newCompleteCommand(job.getKey()).send().join())
        .open();
  }

  private static Path findAgentBpmn() throws IOException {
    if (!Files.isDirectory(AGENT_WORKSPACE)) {
      throw new IllegalStateException(
          "Agent workspace mount not present at " + AGENT_WORKSPACE);
    }
    try (Stream<Path> tree = Files.walk(AGENT_WORKSPACE, 5)) {
      return tree
          .filter(p -> p.toString().endsWith(".bpmn"))
          .findFirst()
          .orElseThrow(
              () ->
                  new IllegalStateException(
                      "No *.bpmn found under "
                          + AGENT_WORKSPACE
                          + " — did the agent save its BPMN somewhere under /workspace?"));
    }
  }
}
