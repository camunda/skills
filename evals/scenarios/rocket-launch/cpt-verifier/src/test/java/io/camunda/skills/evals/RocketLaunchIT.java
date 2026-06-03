package io.camunda.skills.evals;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import io.camunda.client.api.search.enums.ElementInstanceState;
import io.camunda.client.api.search.response.ElementInstance;
import io.camunda.client.api.search.response.SearchResponse;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * Verifier for the rocket-launch scenario.
 *
 * Runs CPT in Spring + remote-runtime mode against the orchestration
 * cluster the agent worked against. The test deploys the agent's
 * BPMN itself (from /agent-workspace), starts an instance, and
 * asserts:
 *   1. The instance completes
 *   2. Completion took at least ~3 seconds (a proxy for the timer
 *      countdown actually firing — a trivial start→end BPMN
 *      completes in milliseconds)
 *   3. At least three element instances completed (start + countdown
 *      activity/activities + end), so the BPMN isn't a degenerate
 *      no-op
 *
 * Independent of the cluster scorer — re-deploys here so the test
 * isn't entangled with CPT's between-test data cleanup.
 */
@SpringBootTest
@CamundaSpringProcessTest
class RocketLaunchIT {

  private static final Path AGENT_WORKSPACE = Path.of("/agent-workspace");

  /** Lower bound for the 3×1s countdown (slack for clock granularity). */
  private static final Duration MIN_DURATION = Duration.ofMillis(2500);

  /** Minimum completed element count (start + ≥1 activity + end = 3). */
  private static final int MIN_COMPLETED_ELEMENTS = 3;

  @Autowired private CamundaClient client;

  @BeforeAll
  static void widenAssertionWindow() {
    // Default is 10s; bump so a 3s countdown + Spring warmup +
    // surefire fork noise doesn't trip the isCompleted() poller.
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
  }

  @Test
  void rocketLaunchCompletes() throws Exception {
    Path bpmn = findAgentBpmn();
    client.newDeployResourceCommand().addResourceFile(bpmn.toString()).send().join();

    Instant before = Instant.now();
    ProcessInstanceEvent instance =
        client
            .newCreateInstanceCommand()
            .bpmnProcessId("RocketLaunch")
            .latestVersion()
            .send()
            .join();

    CamundaAssert.assertThat(instance).isCompleted();
    Duration elapsed = Duration.between(before, Instant.now());

    assertThat(elapsed)
        .as("Process completed too quickly — BPMN likely missing the timer countdown")
        .isGreaterThanOrEqualTo(MIN_DURATION);

    List<ElementInstance> completed = completedElements(instance.getProcessInstanceKey());
    assertThat(completed)
        .as(
            "Expected at least %d completed elements (start + countdown + end); saw %d: %s",
            MIN_COMPLETED_ELEMENTS, completed.size(), elementIds(completed))
        .hasSizeGreaterThanOrEqualTo(MIN_COMPLETED_ELEMENTS);
  }

  private List<ElementInstance> completedElements(long processInstanceKey) {
    SearchResponse<ElementInstance> response =
        client
            .newElementInstanceSearchRequest()
            .filter(
                f ->
                    f.processInstanceKey(processInstanceKey)
                        .state(ElementInstanceState.COMPLETED))
            .send()
            .join();
    return response.items();
  }

  private static List<String> elementIds(List<ElementInstance> instances) {
    return instances.stream().map(ElementInstance::getElementId).toList();
  }

  private static Path findAgentBpmn() throws IOException {
    if (!Files.isDirectory(AGENT_WORKSPACE)) {
      throw new IllegalStateException(
          "Agent workspace mount not present at " + AGENT_WORKSPACE);
    }
    try (Stream<Path> tree = Files.walk(AGENT_WORKSPACE, 5)) {
      return tree
          .filter(p -> p.toString().endsWith(".bpmn"))
          // Skip the skill() tool's plants under skills/ — pick the agent's own
          // BPMN, matching collect_artifacts and the bpmn_lint scorer.
          .filter(p -> !p.toString().contains("/skills/"))
          .findFirst()
          .orElseThrow(
              () ->
                  new IllegalStateException(
                      "No *.bpmn found under "
                          + AGENT_WORKSPACE
                          + " — did the agent save its BPMN under /workspace?"));
    }
  }

  /** Minimal Spring Boot config for the test context. */
  @SpringBootConfiguration
  static class TestApp {}
}
