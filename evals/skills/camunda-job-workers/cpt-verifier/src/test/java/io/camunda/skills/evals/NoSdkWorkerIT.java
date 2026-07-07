package io.camunda.skills.evals;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
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
 * against (the verifier shares its network namespace). The same start → service task → end process
 * shape is exercised in two complementary modes so a red eval localizes the fault:
 *
 * <ul>
 *   <li><b>Integration mode</b> ({@link #realWorkerCompletesInstance}) — deploys the
 *       {@code process-order} fixture and lets the agent's real zero-dependency Node.js worker
 *       (still polling the live cluster) complete the job. Green ⇒ the worker sample works
 *       end-to-end.
 *   <li><b>Process mode</b> ({@link #processModelCompletesWhenJobCompleted}) — deploys a
 *       structurally identical fixture whose job type ({@code model-check}) the agent's worker does
 *       not handle, and CPT completes the job itself via a mock. Green ⇒ the BPMN wiring is sound,
 *       independent of the worker. Distinct job type keeps it race-free against the live worker.
 * </ul>
 *
 * <p>Read together: process green + integration red ⇒ worker bug; both red ⇒ BPMN/fixture bug.
 *
 * <p>The fixtures are committed under {@code src/test/resources} and deployed from the classpath —
 * they are test inputs, not the unit under test, so they are linted once at authoring time rather
 * than regenerated per run. (CPT's embedded/managed mode needs Docker, which the airgapped verifier
 * image omits by design, so both modes run remote.)
 */
@SpringBootTest
@CamundaSpringProcessTest
class NoSdkWorkerIT {

  @Autowired private CamundaClient client;

  @Autowired private CamundaProcessTestContext context;

  @BeforeAll
  static void widenAssertionWindow() {
    // The raw-HTTP worker polls on a ~1s interval; give activation + completion
    // headroom over CPT's 10s default so a healthy worker isn't flagged slow.
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
  }

  /** Integration mode: the agent's real zero-dependency worker drives the job to completion. */
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

  /** Process mode: CPT completes the job, proving the BPMN wiring runs to the end on its own. */
  @Test
  void processModelCompletesWhenJobCompleted() {
    client
        .newDeployResourceCommand()
        .addResourceFromClasspath("NoSdkWorkerModel.bpmn")
        .send()
        .join();

    // `model-check` is not a type the agent's worker polls, so this mock is the
    // only completer — no race with the live worker.
    context.mockJobWorker("model-check").thenComplete();

    ProcessInstanceEvent instance =
        client
            .newCreateInstanceCommand()
            .bpmnProcessId("NoSdkWorkerModel")
            .latestVersion()
            .send()
            .join();

    CamundaAssert.assertThat(instance).isCompleted();
  }

  @SpringBootConfiguration
  static class TestApp {}
}
