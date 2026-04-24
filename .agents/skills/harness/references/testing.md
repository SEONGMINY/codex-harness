# Testing Rules

## Structure

Use given / when / then flow.

```typescript
describe("조건일 때 > 결과여야 한다.", () => {
  // given

  // when

  // then
});
```

## File Names

- Logic: `${file}.test.ts`
- Rendered components: `${file}.test.tsx`

Use `.test.tsx` only when rendering JSX.

## Test Targets

Prefer tests for:

- pure logic
- high-impact branches
- business rules
- regression-prone behavior
- user-visible interaction

Avoid tests that only verify mocks, wrappers, private functions, or implementation details.

## Test Names

Use condition -> result.

Examples:

```typescript
test("같은 값을 다시 선택하면 > 선택이 해제된다.", () => {});
test("선택된 값이 없으면 > 선택한 값이 적용된다.", () => {});
```

Avoid:

- "정상적으로 동작해야 한다"
- implementation terms as the main behavior
- tests that duplicate the implementation

## Coverage

Do not chase coverage percentages.

A good test failing should mean a real defect likely exists.
