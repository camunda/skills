package io.camunda.skills.evals;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import java.time.Duration;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * Verifier for the camunda-job-workers no-SDK worker eval.
 *
 * <p>Runs CPT in <b>remote-runtime mode</b> against the orchestration cluster the agent worked
 * against (the verifier shares its network namespace). Deploys the {@code process-order} fixture,
 * starts an instance, and asserts it completes — with no mock worker, only the agent's real
 * zero-dependency Node.js worker (still polling the live cluster) can drive it, so green ⇒ the
 * worker sample works end-to-end.
 *
 * <p>The fixture is committed under {@code src/test/resources} and deployed from the classpath —
 * it is a test input, not the unit under test, so it is linted once at authoring time rather than
 * regenerated per run. (CPT's embedded/managed mode needs Docker, which the airgapped verifier
 * image omits by design, so the test runs remote.)
 */
@SpringBootTest
@CamundaSpringProcessTest
class NoSdkWorkerIT {

  @Autowired private CamundaClient client;

  @BeforeAll
  static void widenAssertionWindow() {
    // The raw-HTTP worker polls on a ~1s interval; give activation + completion
    // headroom over CPT's 10s default so a healthy worker isn't flagged slow.
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
  }

  /** The agent's real zero-dependency worker drives the job to completion. */
  @Test
  void realWorkerCompletesInstance() {
    client
        .newDeployResourceCommand()
        .addResourceFromClasspath("NoSdkWorkerDemo.bpmn")
        .send()
        .join();

    ProcessInstanceEvent instance =
        client
            .newCreateInstanceCommand()
            .bpmnProcessId("NoSdkWorkerDemo")
            .latestVersion()
            .send()
            .join();

    // No mock worker here — only the agent's real `process-order` worker can
    // complete the job. Completion ⇒ the raw-HTTP worker activated and
    // completed it against the live REST API.
    CamundaAssert.assertThat(instance).isCompleted();
  }

  @SpringBootConfiguration
  static class TestApp {}
}
