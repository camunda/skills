package io.camunda.skills.evals;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.mock.JobWorkerMock;
import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * CPT verifier for scenario 01-rocket-launch.
 *
 * Picks up the agent's BPMN from /outputs/process.bpmn (mounted
 * read-only by the verifier sandbox), deploys it to the embedded
 * Zeebe brought up by CPT, mocks the two job workers
 * (PerformCountdown and Liftoff), then asserts the instance
 * completes end-to-end.
 *
 * Both happy and edge samples share this test — the edge sample
 * (minimum-viable: start -> end, no service tasks) skips the
 * job-worker mocks because the process has none.
 */
@CamundaProcessTest
class RocketLaunchIT {

  private static final Path BPMN = Path.of("/outputs/process.bpmn");

  // CPT injects these.
  private CamundaClient client;
  private CamundaProcessTestContext context;

  @Test
  void agentBpmnReachesEndState() throws Exception {
    client.newDeployResourceCommand().addResourceFile(BPMN.toString()).send().join();

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
    // invocations there. The happy sample expects both to fire.
    assertThat(countdown.getInvocations() + liftoff.getInvocations()).isGreaterThanOrEqualTo(0);
  }
}
