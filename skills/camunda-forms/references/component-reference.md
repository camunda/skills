# Camunda Forms Component Reference

Complete reference for every component type available in Camunda 8.8 forms (schema version 18).

## Common Properties

Every component supports these properties:

| Property | Required | Description |
|----------|----------|-------------|
| `type` | yes | Component type string |
| `id` | yes | Unique identifier within the form |
| `layout` | yes | `{ "row": "row_0", "columns": null }` |
| `conditional` | no | `{ "hide": "=FEEL_expression" }` |
| `properties` | no | Custom key-value properties |

Input components additionally require:

| Property | Required | Description |
|----------|----------|-------------|
| `key` | yes | Process variable name for data binding |
| `label` | yes | Field label displayed to the user |
| `description` | no | Help text below the field |
| `defaultValue` | no | Default value (static or FEEL expression) |
| `readonly` | no | Make field non-editable (`true`/`false`) |
| `disabled` | no | Disable the field (`true`/`false`) |
| `validate` | no | Validation rules object |

## Validation Options

All input components accept a `validate` object:

```json
{
  "validate": {
    "required": true,
    "minLength": 2,
    "maxLength": 100,
    "min": 0,
    "max": 10000,
    "pattern": "^[A-Z]{2}[0-9]+$",
    "validationExpression": "=amount <= budget",
    "requiredErrorMessage": "This field cannot be empty",
    "patternErrorMessage": "Please enter a valid format"
  }
}
```

| Property | Applies to | Description |
|----------|-----------|-------------|
| `required` | all inputs | Field is mandatory |
| `minLength` | textfield, textarea | Minimum string length |
| `maxLength` | textfield, textarea | Maximum string length |
| `min` | number | Minimum numeric value |
| `max` | number | Maximum numeric value |
| `pattern` | textfield | Regular expression pattern |
| `validationExpression` | all inputs | FEEL expression returning boolean |
| `requiredErrorMessage` | all inputs | Custom message for required validation |
| `patternErrorMessage` | textfield | Custom message for pattern validation |

---

## Input Components

### textfield

Single-line text input.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Optional**: `description`, `defaultValue`, `readonly`, `disabled`, `validate`, `conditional`, `properties`
**Validation**: `required`, `minLength`, `maxLength`, `pattern`, `validationExpression`

```json
{
  "type": "textfield",
  "id": "Field_email",
  "key": "email",
  "label": "Email Address",
  "layout": { "row": "row_0", "columns": null },
  "validate": {
    "required": true,
    "pattern": "^[^@]+@[^@]+\\.[^@]+$",
    "patternErrorMessage": "Please enter a valid email"
  }
}
```

### textarea

Multi-line text input.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Optional**: `description`, `defaultValue`, `readonly`, `disabled`, `rows`, `validate`, `conditional`, `properties`
**Validation**: `required`, `minLength`, `maxLength`, `validationExpression`

```json
{
  "type": "textarea",
  "id": "Field_comments",
  "key": "comments",
  "label": "Additional Comments",
  "rows": 5,
  "layout": { "row": "row_0", "columns": null },
  "validate": {
    "maxLength": 500
  }
}
```

### number

Numeric input with optional decimal and increment controls.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Optional**: `description`, `defaultValue`, `readonly`, `disabled`, `decimalDigits`, `increment`, `validate`, `conditional`, `properties`
**Validation**: `required`, `min`, `max`, `validationExpression`

```json
{
  "type": "number",
  "id": "Field_amount",
  "key": "orderAmount",
  "label": "Order Amount",
  "decimalDigits": 2,
  "increment": "0.01",
  "layout": { "row": "row_0", "columns": null },
  "validate": {
    "required": true,
    "min": 0,
    "max": 999999.99
  }
}
```

### checkbox

Boolean checkbox for true/false input.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Optional**: `description`, `defaultValue`, `disabled`, `validate`, `conditional`, `properties`
**Validation**: `required`

```json
{
  "type": "checkbox",
  "id": "Field_terms",
  "key": "acceptedTerms",
  "label": "I accept the terms and conditions",
  "layout": { "row": "row_0", "columns": null },
  "validate": {
    "required": true
  }
}
```

### checklist

Multiple checkboxes for selecting several options. Output is a list of selected values.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Values**: provide `values` (static) or `valuesExpression` (dynamic FEEL)
**Optional**: `description`, `disabled`, `validate`, `conditional`, `properties`
**Validation**: `required`

```json
{
  "type": "checklist",
  "id": "Field_features",
  "key": "selectedFeatures",
  "label": "Select Features",
  "layout": { "row": "row_0", "columns": null },
  "values": [
    { "label": "Feature A", "value": "featureA" },
    { "label": "Feature B", "value": "featureB" },
    { "label": "Feature C", "value": "featureC" }
  ]
}
```

### radio

Radio button group for single selection from predefined options.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Values**: provide `values` (static) or `valuesExpression` (dynamic FEEL)
**Optional**: `description`, `defaultValue`, `disabled`, `validate`, `conditional`, `properties`
**Validation**: `required`

```json
{
  "type": "radio",
  "id": "Field_priority",
  "key": "priority",
  "label": "Priority Level",
  "layout": { "row": "row_0", "columns": null },
  "values": [
    { "label": "Low", "value": "low" },
    { "label": "Medium", "value": "medium" },
    { "label": "High", "value": "high" }
  ],
  "validate": { "required": true }
}
```

### select

Dropdown selection for single choice.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Values**: provide `values` (static) or `valuesExpression` (dynamic FEEL)
**Optional**: `description`, `defaultValue`, `readonly`, `disabled`, `searchable`, `validate`, `conditional`, `properties`
**Validation**: `required`

Static values:
```json
{
  "type": "select",
  "id": "Field_category",
  "key": "productCategory",
  "label": "Product Category",
  "layout": { "row": "row_0", "columns": null },
  "values": [
    { "label": "Electronics", "value": "electronics" },
    { "label": "Clothing", "value": "clothing" },
    { "label": "Books", "value": "books" }
  ],
  "validate": { "required": true }
}
```

Dynamic values from process variable:
```json
{
  "type": "select",
  "id": "Field_dynamic",
  "key": "selectedItem",
  "label": "Choose Item",
  "layout": { "row": "row_0", "columns": null },
  "valuesExpression": "=availableItems",
  "validate": { "required": true }
}
```

The process variable must contain a list of `{ "label": "...", "value": "..." }` objects.

### taglist

Multi-select tag input. Output is a list of selected values.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Values**: provide `values` (static) or `valuesExpression` (dynamic FEEL)
**Optional**: `description`, `disabled`, `validate`, `conditional`, `properties`
**Validation**: `required`

```json
{
  "type": "taglist",
  "id": "Field_skills",
  "key": "selectedSkills",
  "label": "Skills",
  "layout": { "row": "row_0", "columns": null },
  "values": [
    { "label": "Java", "value": "java" },
    { "label": "Python", "value": "python" },
    { "label": "Go", "value": "go" }
  ]
}
```

### datetime

Date and/or time picker.

**Required**: `type`, `id`, `key`, `label`, `layout`
**Optional**: `description`, `defaultValue`, `readonly`, `disabled`, `subtype`, `dateLabel`, `timeLabel`, `timeSerializingFormat`, `validate`, `conditional`, `properties`
**Validation**: `required`

- `subtype`: `"date"`, `"time"`, or `"datetime"` (default: `"datetime"`)
- `timeSerializingFormat`: `"utc_offset"` or `"utc_normalized"`

```json
{
  "type": "datetime",
  "id": "Field_deadline",
  "key": "deadline",
  "label": "Deadline",
  "dateLabel": "Select Date",
  "timeLabel": "Select Time",
  "timeSerializingFormat": "utc_offset",
  "layout": { "row": "row_0", "columns": null },
  "validate": {
    "required": true
  }
}
```

---

## Display Components

### text

Render static text or markdown. Does not bind to a variable.

**Required**: `type`, `id`, `text`, `layout`
**Optional**: `conditional`, `properties`

```json
{
  "type": "text",
  "id": "Text_header",
  "text": "### Section Title\n\nPlease fill in the details below.",
  "layout": { "row": "row_0", "columns": null }
}
```

### html

Render raw HTML content. Does not bind to a variable. Use cautiously.

**Required**: `type`, `id`, `content`, `layout`
**Optional**: `conditional`, `properties`

```json
{
  "type": "html",
  "id": "Html_notice",
  "content": "<div style=\"color: red;\"><strong>Important:</strong> This action cannot be undone.</div>",
  "layout": { "row": "row_0", "columns": null }
}
```

### image

Display an image from a URL or expression. Does not bind to a variable.

**Required**: `type`, `id`, `source`, `layout`
**Optional**: `alt`, `conditional`, `properties`

```json
{
  "type": "image",
  "id": "Image_logo",
  "source": "https://example.com/logo.png",
  "alt": "Company Logo",
  "layout": { "row": "row_0", "columns": null }
}
```

### separator

Horizontal line to visually divide sections. No data binding.

**Required**: `type`, `id`, `layout`
**Optional**: `conditional`, `properties`

```json
{
  "type": "separator",
  "id": "Separator_1",
  "layout": { "row": "row_0", "columns": null }
}
```

### button

Action button, typically used for form submission.

**Required**: `type`, `id`, `label`, `layout`
**Optional**: `action`, `conditional`, `properties`

- `action`: `"submit"` (default) or `"reset"`

```json
{
  "type": "button",
  "id": "Button_submit",
  "label": "Submit",
  "action": "submit",
  "layout": { "row": "row_0", "columns": null }
}
```

---

## Layout Components

### group

Container for grouping related components. Renders a labeled section with nested fields.

**Required**: `type`, `id`, `label`, `components`, `layout`
**Optional**: `showOutline`, `conditional`, `properties`

```json
{
  "type": "group",
  "id": "Group_address",
  "label": "Address",
  "showOutline": true,
  "layout": { "row": "row_0", "columns": null },
  "components": [
    {
      "type": "textfield",
      "id": "Field_street",
      "key": "street",
      "label": "Street",
      "layout": { "row": "row_g0", "columns": null }
    },
    {
      "type": "textfield",
      "id": "Field_city",
      "key": "city",
      "label": "City",
      "layout": { "row": "row_g1", "columns": null }
    }
  ]
}
```

### spacer

Add vertical spacing between components. No data binding.

**Required**: `type`, `id`, `layout`
**Optional**: `height`, `conditional`, `properties`

```json
{
  "type": "spacer",
  "id": "Spacer_1",
  "height": 32,
  "layout": { "row": "row_0", "columns": null }
}
```

### dynamiclist

Repeatable section that allows users to add/remove rows of fields. Output is a list of objects.

**Required**: `type`, `id`, `key`, `label`, `components`, `layout`
**Optional**: `defaultValue`, `disableCollapse`, `nonCollapsible`, `validate`, `conditional`, `properties`

```json
{
  "type": "dynamiclist",
  "id": "DynamicList_items",
  "key": "lineItems",
  "label": "Order Items",
  "layout": { "row": "row_0", "columns": null },
  "components": [
    {
      "type": "textfield",
      "id": "Field_itemName",
      "key": "itemName",
      "label": "Item Name",
      "layout": { "row": "row_dl0", "columns": null }
    },
    {
      "type": "number",
      "id": "Field_quantity",
      "key": "quantity",
      "label": "Quantity",
      "layout": { "row": "row_dl0", "columns": null },
      "validate": { "required": true, "min": 1 }
    }
  ]
}
```

### iframe

Embed an external page or application. Does not bind to a variable.

**Required**: `type`, `id`, `url`, `layout`
**Optional**: `height`, `title`, `conditional`, `properties`

```json
{
  "type": "iframe",
  "id": "Iframe_preview",
  "url": "https://example.com/preview",
  "height": "400px",
  "title": "Document Preview",
  "layout": { "row": "row_0", "columns": null }
}
```

### table

Display tabular data. Typically used for read-only data presentation.

**Required**: `type`, `id`, `layout`
**Optional**: `label`, `dataSource`, `columns`, `rowCount`, `conditional`, `properties`

- `dataSource`: FEEL expression pointing to a list variable
- `columns`: array of `{ "key": "...", "label": "..." }` definitions

```json
{
  "type": "table",
  "id": "Table_orders",
  "label": "Recent Orders",
  "dataSource": "=orderList",
  "columns": [
    { "key": "orderId", "label": "Order ID" },
    { "key": "customer", "label": "Customer" },
    { "key": "total", "label": "Total" }
  ],
  "layout": { "row": "row_0", "columns": null }
}
```
