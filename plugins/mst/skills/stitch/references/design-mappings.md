# Stitch Design Mappings

Use this reference to translate abstract UX intent into concrete visual direction.

## Intent -> Layout

| Intent keyword | Layout direction | Notes |
|---|---|---|
| dashboard | 12-column grid + persistent sidebar + top summary strip | Prioritize scanability and data hierarchy |
| admin | dense table-first layout + filter rail | Keep controls visible and sticky |
| landing | hero-first + trust blocks + CTA repetition | Emphasize conversion path |
| onboarding | progressive stepper + helper panel | Reduce decision load per step |
| settings | sectioned form + local nav tabs | Group by account, privacy, billing |
| analytics | KPI cards + trend panels + drilldown region | Pair summary with detail |
| marketplace | faceted search + card grid + compare state | Focus on discovery |
| profile | identity header + activity timeline + edit drawer | Keep account actions contextual |
| chat | split layout (thread list + conversation) | Prioritize message readability |
| editor | canvas-center + inspector-right + toolbar-top | Reserve whitespace around canvas |

## Tone -> Color + Contrast

| Tone keyword | Palette direction | Contrast strategy |
|---|---|---|
| minimal | neutral surfaces + 1 restrained accent | high text contrast, low chroma UI |
| modern | cool neutrals + vivid accent | accent only for actions/states |
| playful | saturated secondary accents | clear semantic color lanes |
| premium | deep base + metallic-like highlights | generous spacing + restrained color count |
| corporate | desaturated blues/charcoals | stability over novelty |
| warm | soft amber/terracotta accents | avoid over-dark body text |
| dark | dark surfaces with raised layers | boost border + focus contrast |

## Component Weight Mapping

| Priority | Treatment |
|---|---|
| primary action | filled button + strongest contrast |
| secondary action | outline/tonal button |
| destructive | dedicated danger hue + explicit label |
| passive info | subtle container + lower visual weight |
| alerts | icon + color + title + action |

## Typography Mapping

| Product feel | Font strategy | Scale |
|---|---|---|
| product UI | neutral sans | 14/16 body, 20-32 headings |
| editorial | serif headings + sans UI text | stronger heading contrast |
| enterprise | highly legible sans | conservative scale steps |
| consumer | expressive display + clean body | larger hero sizes |

## Density Mapping

| Density | Spacing rhythm | Target |
|---|---|---|
| compact | 4/8 spacing system | data-heavy workflows |
| balanced | 8/12 spacing system | general product screens |
| airy | 12/16 spacing system | marketing and storytelling |

## Motion + State

- Prefer 120-220ms easing for common transitions.
- Animate hierarchy changes (drawers, modals, accordions), not every element.
- Preserve reduced-motion accessibility behavior.

## Accessibility Guardrails

- Minimum text contrast: WCAG AA baseline.
- Never encode status by color alone; pair with icon/text.
- Keep keyboard focus ring visible across all themes.
- Ensure touch targets are at least 40px.

## Prompt Block Template

Use this block before generation/editing prompts:

```markdown
**DESIGN SYSTEM**
- Tone: {tone}
- Density: {density}
- Primary color direction: {palette}
- Typography: {typography}
- Components to emphasize: {component_priorities}

**Page Structure**
- Primary goal: {goal}
- Core sections: {section_list}
- Critical interactions: {interaction_list}
- Responsive behavior: {mobile_behavior}
```
