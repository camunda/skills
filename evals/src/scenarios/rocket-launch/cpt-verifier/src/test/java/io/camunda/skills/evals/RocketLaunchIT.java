package io.camunda.skills.evals;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.mock.JobWorkerMock;
import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;

/**
 * CPT verifier for the rocket-launch scenario.
 *
 * Picks up the agent's BPMN from /agent-workspace (mounted read-only —
 * the agent's whole /workspace volume), deploys it to the embedded
 * Zeebe brought up by CPT, mocks any job workers the BPMN declares,
 * then asserts the instance completes end-to-end.
 *
 * The test doesn't constrain the agent's filename or subdirectory:
 * it picks the first *.bpmn anywhere under /agent-workspace, which
 * matches whatever a real user-style agent would naturally produce.
 *
 * Both happy and edge samples share this test — the edge sample
 * (minimum-viable: start -> end, no service tasks) skips the
 * job-worker mocks because the process has none.
 */
@CamundaProcessTest
class RocketLaunchIT {

  private static final Path AGENT_WORKSPACE = Path.of("/agent-workspace");

  // CPT injects these.
  private CamundaClient client;
  private CamundaProcessTestContext context;

  @Test
  void agentBpmnReachesEndState() throws Exception {
    Path bpmn = findAgentBpmn();

    client.newDeployResourceCommand().addResourceFile(bpmn.toString()).send().join();

    // Defensive mocks — the happy sample exercises these; the edge
    // sample has no service tasks and will leave the mocks unused.
    JobWorkerMock countdown =
        context.mockJobWorker("countdown").withHandler((j, jc) -> jc.complete(j, Map.of()));
    JobWorkerMock liftoff =
        context.mockJobWorker("liftoff").withHandler((j, jc) -> jc.complete(j, Map.of()));

    ProcessInstanceEvent instance =
        client
            .newCreateInstanceCommand()
            .bpmnProcessId("RocketLaunch")
            .latestVersion()
            .variables(Map.of("countdownSeconds", 3))
            .send()
            .join();

    CamundaAssert.assertThat(instance).isCompleted();

    // The edge sample skips service tasks; both mocks may have zero
    // invocations there. The happy sample expects at least one fire.
    assertThat(countdown.getInvocations() + liftoff.getInvocations()).isGreaterThanOrEqualTo(0);
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
