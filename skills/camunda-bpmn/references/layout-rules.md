# BPMN Diagram Layout Rules

Rules for managing the `<bpmndi:BPMNDiagram>` section with element coordinates.

## Standard Element Sizes

| Element Type | Width | Height |
|-------------|-------|--------|
| Start Event | 36 | 36 |
| End Event | 36 | 36 |
| Intermediate Event | 36 | 36 |
| Boundary Event | 36 | 36 |
| Task (any type) | 100 | 80 |
| Gateway | 50 | 50 |
| Subprocess | varies | varies |

## Spacing Rules

- **Horizontal spacing** between elements: 150px (center-to-center ~200px for tasks)
- **Vertical spacing** for parallel branches: 100px between branch centers
- **Minimum gap** between elements: 20px (to avoid overlapping warnings)
- **Subprocess padding**: 50px inside boundaries on all sides

## Layout Patterns

### Linear Flow (left to right)

```
Start(152,102) → Task(240,80) → Gateway(390,95) → End(490,102)
```

```xml
<bpmndi:BPMNShape id="Start_di" bpmnElement="Start">
  <dc:Bounds x="152" y="102" width="36" height="36" />
</bpmndi:BPMNShape>
<bpmndi:BPMNShape id="Task_di" bpmnElement="Task">
  <dc:Bounds x="240" y="80" width="100" height="80" />
</bpmndi:BPMNShape>
<bpmndi:BPMNShape id="Gateway_di" bpmnElement="Gateway">
  <dc:Bounds x="390" y="95" width="50" height="50" />
</bpmndi:BPMNShape>
<bpmndi:BPMNShape id="End_di" bpmnElement="End">
  <dc:Bounds x="490" y="102" width="36" height="36" />
</bpmndi:BPMNShape>
```

### Parallel Branches

Center the fork gateway vertically. Branch up and down symmetrically:

```
                    ┌─ Task_A (y=0) ──┐
Start → Fork(y=95) ┤                  ├ Join → End
                    └─ Task_B (y=190) ┘
```

Upper branch: `y = forkY - verticalSpacing/2 - taskHeight/2`
Lower branch: `y = forkY + verticalSpacing/2 - taskHeight/2`

### Exclusive Gateway with Two Outcomes

```
                              ┌─ End_Approved (y=80)
Task → Gateway(390,95) ──────┤
                              └─ End_Rejected (y=170)
```

### Centering Formulas

- **Center event vertically with task**: `eventY = taskY + (taskHeight - eventHeight) / 2`
  - Example: task at y=80 (h=80), event at y=80 + (80-36)/2 = y=102
- **Center gateway vertically with task**: `gatewayY = taskY + (taskHeight - gatewayHeight) / 2`
  - Example: task at y=80 (h=80), gateway at y=80 + (80-50)/2 = y=95

## Sequence Flow Edges

Edges connect shapes via waypoints. Simple horizontal connections need two waypoints:

```xml
<bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1">
  <di:waypoint x="188" y="120" />  <!-- Right edge of start event -->
  <di:waypoint x="240" y="120" />  <!-- Left edge of task -->
</bpmndi:BPMNEdge>
```

### Waypoint Calculations

- **From event right edge**: `x = eventX + eventWidth`, `y = eventY + eventHeight/2`
- **To task left edge**: `x = taskX`, `y = taskY + taskHeight/2`
- **From task right edge**: `x = taskX + taskWidth`, `y = taskY + taskHeight/2`
- **From gateway right**: `x = gatewayX + gatewayWidth`, `y = gatewayY + gatewayHeight/2`
- **From gateway bottom**: `x = gatewayX + gatewayWidth/2`, `y = gatewayY + gatewayHeight`

For flows that change direction (e.g., from gateway down to a branch), use intermediate waypoints:

```xml
<bpmndi:BPMNEdge id="Flow_Down_di" bpmnElement="Flow_Down">
  <di:waypoint x="415" y="145" />  <!-- Bottom of gateway -->
  <di:waypoint x="415" y="230" />  <!-- Intermediate: go down -->
  <di:waypoint x="490" y="230" />  <!-- Left edge of lower task -->
</bpmndi:BPMNEdge>
```

## Boundary Event Positioning

Place boundary events on the bottom edge of the attached task:

```xml
<!-- Boundary event centered on bottom edge of task at (240, 80, 100, 80) -->
<bpmndi:BPMNShape id="Boundary_di" bpmnElement="Boundary_Timer">
  <dc:Bounds x="272" y="142" width="36" height="36" />
</bpmndi:BPMNShape>
```

Formula: `x = taskX + taskWidth/2 - eventWidth/2`, `y = taskY + taskHeight - eventHeight/2`

## Subprocess Layout

Subprocess bounds must enclose all internal elements with padding:

```xml
<bpmndi:BPMNShape id="Sub_di" bpmnElement="Sub_Process" isExpanded="true">
  <dc:Bounds x="200" y="50" width="400" height="200" />
</bpmndi:BPMNShape>
```

Internal elements use coordinates relative to the diagram (not the subprocess). Ensure all internal shapes fall within the subprocess bounds with ≥50px padding.

## Incremental Layout

When modifying existing processes:
1. **Only touch DI entries for new/moved elements** — preserve existing layout
2. **Insert new elements** in the flow by shifting downstream elements right
3. **Add branches** by shifting existing elements to make room
4. **Never recompute the entire layout** unless explicitly asked — this destroys manual positioning

## When Layout Is Badly Broken

If element coordinates are badly off (overlapping shapes, runaway waypoints), don't try to patch — re-derive coordinates from scratch using the standard sizes and spacing rules above, walking the flow left-to-right. Open the result in Modeler to sanity-check before declaring it done.
