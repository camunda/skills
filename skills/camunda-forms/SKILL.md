---
name: camunda-forms
description: |
  Use this skill to create and edit Camunda Form JSON schemas for user tasks and start events in Camunda 8.

  Use for: field layouts (textfield, textarea, number, checkbox, select, radio, datetime, etc.), validation rules (required, pattern, min/max), conditional visibility via FEEL expressions, dynamic dropdown values via valuesExpression, default-value FEEL expressions, multi-row form structure, process-variable bindings.

  Do not use for: writing the BPMN around a user task (use camunda-bpmn), or writing the FEEL expressions referenced by form fields (use camunda-feel).

  **Workflow skill** — produces a .form JSON file linked from a BPMN user task or start event.
---

# Camunda Forms

Create Camunda Form JSON schemas for user tasks and start events in Camunda 8.8+.

## Prerequisites

- Camunda 8.8+ cluster

## Cross-References

- **camunda-bpmn**: Use when linking forms to user tasks via `<zeebe:formDefinition formId="..."/>`
- **camunda-feel**: Use for form validation expressions and conditional visibility logic

## Instructions

### Form Basics

Camunda Forms are JSON files with `.form` extension (not `.json`). Link to BPMN user tasks via the form's `id` field, which must match the `formId` attribute on `<zeebe:formDefinition formId="..."/>` inside the user task. The user task itself must also include `<zeebe:userTask/>` (the Camunda user task implementation). Don't link via the older `formKey` attribute — that's the deprecated job-worker user task, removed in Camunda 8.10. See **camunda-bpmn** § Form Definition for the BPMN side.

### Form Structure

**Example** — minimal form skeleton:

```json
{
  "components": [],
  "executionPlatform": "Camunda Cloud",
  "executionPlatformVersion": "8.8.0",
  "exporter": { "name": "Camunda Modeler", "version": "5.34.0" },
  "schemaVersion": 18,
  "id": "my-form-id",
  "type": "default"
}
```

All metadata fields are required. Use `schemaVersion: 18` and `executionPlatformVersion: "8.8.0"`.

### Components

Every component requires `type`, `id`, and `layout`. Input components also need `key` (maps to process variable name) and `label`.

```json
{
  "type": "textfield",
  "id": "Field_Name",
  "key": "customerName",
  "label": "Customer Name",
  "layout": { "row": "row_0", "columns": null }
}
```

**Input components**: `textfield`, `textarea`, `number`, `checkbox`, `checklist`, `radio`, `select`, `taglist`, `datetime`

**Display components**: `text` (markdown), `html`, `image`, `separator`, `button`

**Layout components**: `group`, `spacer`

See `references/component-reference.md` for complete properties of each component type.

### Layout

Components are arranged in rows. Place components in the same row to display them side-by-side:

```json
{ "type": "textfield", "id": "F1", "key": "firstName", "label": "First Name", "layout": { "row": "row_0", "columns": null } },
{ "type": "textfield", "id": "F2", "key": "lastName", "label": "Last Name", "layout": { "row": "row_0", "columns": null } }
```

### Variable Binding

The `key` property maps a form field to a process variable:
- On load: field is pre-populated from the variable if it exists
- On submit: field value is written back to the variable

### Validation

```json
{
  "validate": {
    "required": true,
    "minLength": 2,
    "maxLength": 100,
    "min": 0,
    "max": 10000,
    "pattern": "^[A-Z]{2}[0-9]+$",
    "validationExpression": "=amount <= budget"
  }
}
```

Custom error messages: `requiredErrorMessage`, `patternErrorMessage`.

### Conditional Visibility

Hide or show fields based on other field values using FEEL:

```json
{
  "conditional": {
    "hide": "=approved = false"
  }
}
```

The expression is evaluated against all form field values and process variables.

### Select / Radio / Checklist Options

Static values:
```json
{
  "type": "select",
  "values": [
    { "label": "Low", "value": "low" },
    { "label": "Medium", "value": "medium" },
    { "label": "High", "value": "high" }
  ]
}
```

Dynamic values from process variable:
```json
{
  "type": "select",
  "valuesExpression": "=departments"
}
```

The variable should be a list of `{label, value}` objects.

### Read-Only Fields

Display data without allowing edits:
```json
{
  "type": "textfield",
  "key": "orderId",
  "label": "Order ID",
  "readonly": true
}
```

### Text / Markdown

Display static text or instructions using markdown:
```json
{
  "type": "text",
  "text": "### Review Details\n\nPlease review the information below.",
  "id": "Text_Header",
  "layout": { "row": "row_0", "columns": null }
}
```

### Groups

Organize related fields:
```json
{
  "type": "group",
  "label": "Contact Information",
  "components": [
    { "type": "textfield", "id": "F1", "key": "email", "label": "Email", "layout": { "row": "row_g0", "columns": null } },
    { "type": "textfield", "id": "F2", "key": "phone", "label": "Phone", "layout": { "row": "row_g1", "columns": null } }
  ],
  "id": "Group_Contact",
  "layout": { "row": "row_1", "columns": null }
}
```

### Output Format

Generate complete `.form` JSON files. Ensure:
- All `id` values are unique within the form
- `key` values match expected process variable names
- `layout.row` values increment sequentially (`row_0`, `row_1`, ...)
- Metadata fields are present and correct

## Troubleshooting

- **Form doesn't appear in Tasklist** — verify the user task in BPMN includes `<zeebe:userTask/>` and `<zeebe:formDefinition formId="..."/>` matching the form's `id` field. The legacy `formKey` attribute was removed in Camunda 8.10.
- **`schemaVersion` mismatch error** — set `schemaVersion: 18` and `executionPlatformVersion: "8.8.0"`; older values are rejected by 8.8+ clusters.
- **Conditional field always hidden** — `conditional.hide` is a FEEL expression that returns true to hide. Forgetting the `=` prefix turns it into a literal string. See **camunda-feel** § Common Patterns for the FEEL side.

## References

For detailed reference material, read from `references/`:
- [component-reference.md](references/component-reference.md) — complete properties and examples for every component type (textfield, number, select, datetime, etc.)
