package io.camunda.skills.evals;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ProcessInstanceEvent;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * Behavioral verifier for camunda-bpmn skill evals.
 *
 * Which test runs is selected by the ``eval.sample.id`` system property
 * (passed by the cpt_scorer). Each sample enables exactly one test via
 * {@code @EnabledIfSystemProperty}:
 *
 *   linear-invoice-review      → reviewInvoiceUserTaskIsReached
 *   exclusive-gateway-routing  → xorGatewayRoutesCorrectly (parameterized, 2 cases)
 */
@SpringBootTest
@CamundaSpringProcessTest
class CamundaBpmnIT {

  private static final Path AGENT_WORKSPACE = Path.of("/agent-workspace");

  @Autowired
  private CamundaClient client;

  // Field injection so CamundaProcessTestContext works in @ParameterizedTest methods
  // (parameter injection is consumed by @CsvSource and can't be mixed with extensions).
  @Autowired
  private CamundaProcessTestContext context;

  @BeforeAll
  static void setup() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
  }

  // ─── linear-invoice-review ──────────────────────────────────────────────

  @Test
  void reviewInvoiceUserTaskIsReached() throws Exception {
    deploy();

    // Auto-complete the service task so the process can reach isCompleted()
    context.mockJobWorker("record-decision").thenComplete();

    ProcessInstanceEvent instance =
        client.newCreateInstanceCommand().bpmnProcessId("invoice-approval").latestVersion()
            .send().join();

    // Process should reach the ReviewInvoice user task (element id from the sample prompt)
    CamundaAssert.assertThat(instance).hasActiveElements("ReviewInvoice");
    context.completeUserTask("ReviewInvoice");
    CamundaAssert.assertThat(instance).isCompleted();
  }

  // ─── exclusive-gateway-routing ──────────────────────────────────────────

  @ParameterizedTest(name = "{3}")
  @CsvSource({
    "1500, manual-approval, auto-approval, amount > 1000 routes to manual-approval",
    "100, auto-approval, manual-approval, amount <= 1000 routes to auto-approval"
  })
  void xorGatewayRoutesCorrectly(int amount, String expectedType, String unexpectedType, String label)
      throws Exception {
    deploy();

    // Auto-complete the service tasks that bracket the gateway
    context.mockJobWorker("validate-order").thenComplete();
    context.mockJobWorker("send-confirmation").thenComplete();

    ProcessInstanceEvent instance =
        client.newCreateInstanceCommand()
            .bpmnProcessId("order-fulfillment")
            .latestVersion()
            .variables(Map.of("amount", amount))
            .send()
            .join();

    // After validate-order auto-completes, the XOR gateway fires.
    // Assert the expected branch produced a job (job type from the sample prompt).
    Awaitility.await()
        .atMost(10, TimeUnit.SECONDS)
        .untilAsserted(
            () ->
                assertThat(
                        client
                            .newJobSearchRequest()
                            .filter(
                                f ->
                                    f.processInstanceKey(instance.getProcessInstanceKey())
                                        .type(expectedType))
                            .send()
                            .join()
                            .items())
                    .as("Expected job type '%s' for amount=%d", expectedType, amount)
                    .isNotEmpty());

    // Assert the other branch was not taken
    assertThat(
            client
                .newJobSearchRequest()
                .filter(
                    f ->
                        f.processInstanceKey(instance.getProcessInstanceKey())
                            .type(unexpectedType))
                .send()
                .join()
                .items())
        .as("Unexpected job type '%s' should not be active for amount=%d", unexpectedType, amount)
        .isEmpty();

    // Complete the routed branch and verify the full process runs to completion
    context.completeJob(expectedType);
    CamundaAssert.assertThat(instance).isCompleted();
  }

  // ─── helpers ────────────────────────────────────────────────────────────

  private void deploy() throws Exception {
    Path bpmn = findAgentBpmn();
    client.newDeployResourceCommand().addResourceFile(bpmn.toString()).send().join();
  }

  private static Path findAgentBpmn() throws IOException {
    if (!Files.isDirectory(AGENT_WORKSPACE)) {
      throw new IllegalStateException("Agent workspace not present at " + AGENT_WORKSPACE);
    }
    try (Stream<Path> tree = Files.walk(AGENT_WORKSPACE, 5)) {
      return tree
          .filter(p -> p.toString().endsWith(".bpmn"))
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

  @SpringBootConfiguration
  static class TestApp {}
}
