# Examples

Reference BPMN processes and forms demonstrating Camunda 8 patterns.

## Invoice Approval

A simple approval workflow demonstrating:

- **invoice-approval.bpmn**: User task with form, exclusive gateway, service task with I/O mappings
- **approval-form.form**: Conditional visibility, read-only fields, validation

### Process Flow

1. **Invoice received** (start event)
2. **Review invoice** (user task with approval form)
3. **Approved?** (exclusive gateway)
   - Yes → **Notify accounting** (service task) → **Invoice approved** (end)
   - No → **Invoice rejected** (end)

### Variables

- `invoiceId`: Invoice identifier
- `vendor`: Vendor name
- `amount`: Invoice amount
- `description`: Invoice description
- `approved`: Boolean set by the reviewer
- `comments`: Optional rejection reason
