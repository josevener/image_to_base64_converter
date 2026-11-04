# Task Specification Authoring

Use this guide when creating a task specification for a development request. Produce a complete, implementation-ready Markdown document using the structure below. Keep the language specific to the requested change; do not leave placeholders in the final task specification.

## Output location and naming

- Save every generated task specification in `.agents/task_specs/`; create the directory when it does not exist.
- Name each file with a concise, descriptive `snake_case` name and the `.md` extension, for example `.agents/task_specs/marketplace_empty_states.md`.
- Do not place generated task specifications directly in `.agents/` or elsewhere in the repository.

## Required format

```md
**Task Title**
<Clear, concise task title>

**Git Branch/Commit Name**
<lowercase_snake_case_name>

**Task Type**
<Enhancement | Bug Fix | New Feature | Refactor | Maintenance | Research>

**Goal**
<The desired outcome and business value.>

**Problem**
<The current limitation, defect, or user need.>

**UI Changes**
<User-facing screens, controls, behavior, and help text. State "None" when no UI work is needed.>

**User Flow**
<Numbered end-to-end flow from the user action through the expected system result.>

**Technical Notes**
<Implementation guidance organized by relevant areas, such as Backend, Frontend, Data, API, Validation Rules, Permissions, and Observability.>

**Edge Cases**
<Specific unusual, missing, invalid, duplicate, concurrent, or authorization cases that must be handled safely.>

**TDD Scenarios**

**Positive Cases**
Given <initial state>
When <action>
Then <expected outcome>

**Negative Cases**
Given <initial state>
When <invalid or exceptional action>
Then <safe expected outcome>

**Unit Test Requirement**
<Required | Not Required>

Suggested Test Targets:
<Relevant modules, services, controllers, components, or helpers>

Reason:
<Why automated tests are or are not appropriate.>

**User Guide Manual Impact**
<Review Required | No Impact Expected>

Reason:
<Whether user-facing behavior, configuration, or workflows need documentation updates.>

**Done Definition**
<Concrete, verifiable completion criteria, including implementation, validation, tests, and documentation where applicable.>
```

## Authoring rules

- Write requirements as observable behavior, not vague implementation intent.
- Include every affected user role, permission boundary, integration, and data rule known from the request.
- Use the actual field, endpoint, screen, and service names when available; otherwise state the assumption explicitly.
- For changes that match, import, synchronize, update, or delete data, specify duplicate handling, missing identifiers, invalid inputs, and non-destructive failure behavior.
- Provide at least one positive and one negative Given/When/Then scenario whenever **Unit Test Requirement** is `Required`.
- Make **Done Definition** independently verifiable. It must cover the requested functionality, safe handling of listed edge cases, tests, and documentation review when applicable.
- Do not prescribe an implementation detail when the desired behavior is enough to guide development, unless the request explicitly requires that detail.
