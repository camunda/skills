package io.camunda.tests;

import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import org.junit.jupiter.params.ParameterizedTest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
@CamundaSpringProcessTest
@TestDeployment(
    resources = {
      "processes/ai-agent-chat-with-tools.bpmn",
      "forms/ai-agent-chat-initial-request.form",
      "forms/ai-agent-chat-user-feedback.form"
    })
public class ProcessTest {

  @Autowired private TestCaseRunner testCaseRunner;

  @ParameterizedTest(name = "{0}")
  @TestCaseSource(directory = "/scenarios")
  void shouldPass(final TestCase testCase, final String fileName) {
    testCaseRunner.run(testCase);
  }
}
