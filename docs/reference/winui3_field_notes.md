# WinUI 3 / Windows App SDK — field notes

**Purpose:** non-obvious WinUI 3 and Windows App SDK specifics that our desktop app
(`services/ui_winui/BlarAI.Desktop.csproj` — WinUI 3, Windows App SDK 1.8, .NET 8, unpackaged
self-contained) can trip on. These are *distilled and verified against our own tree*, not a general tutorial.

**Provenance (per the "documentation is not evidence" doctrine — `CLAUDE.md` `<seams>`):**
The starting material was the instruction text of three skills in `microsoft/win-dev-skills`
(`winui-design`, `winui-code-review`, and its `quality-rules` reference), MIT-licensed, read once on
2026-07-20. **We did not adopt that repository** — it ships a binary that performs silent detached network
fetches, and its automation depends on a toolchain we rejected (see Vikunja #982 for the full disposition).
This file is our own notes: every item below was checked against our actual XAML/C# before being written
down, and the "Verified in our tree" column says what we found. Where their generic advice did not match our
reality, our reality governs.

**Artifacts actually read to produce this file:** `winui-design/SKILL.md`, `winui-code-review/SKILL.md`,
`winui-code-review/references/quality-rules.md` (skill instruction text); and on our side,
`services/ui_winui/MainWindow.xaml`, `MainWindow.xaml.cs`, `App.xaml`. Not read: the skills' compiled
binaries or reference files we did not fetch.

---

## The landmines, checked against our tree

| # | Landmine | Why it bites | Verified in our tree (2026-07-20) |
|---|---|---|---|
| 1 | **`AppWindow.Resize` takes PHYSICAL PIXELS, not DIPs** | On a high-DPI display the window comes out smaller than intended by the scale factor. At 150% a `Resize(1100,760)` yields ~733×507 DIPs of content. | **PRESENT — latent defect.** `MainWindow.xaml.cs:130` hardcodes `Resize(new SizeInt32(1100, 760))` with no DPI multiply. This laptop runs high-DPI by default. Ticketed. |
| 2 | **`x:Bind` defaults to `OneTime`** | A binding with no `Mode=` never updates after first render — silent stale UI, not an error. | **MIXED — needs review.** 20 of ~54 bindings set `Mode`. The unmoded ones split: `Tag`/`ItemsSource` bindings where OneTime is correct, and several per-item `DataTemplate` property bindings (e.g. `Text="{x:Bind DisplayTitle}"`) that are stale-risk if the property mutates post-render. Ticketed for a review pass. |
| 3 | **Custom theme dictionaries must define `HighContrast` explicitly** | Custom semantic brushes that only exist in `Light`/`Dark` do not adapt in High Contrast mode → possible unreadable UI for those users. | **PRESENT — accessibility gap.** `App.xaml` defines `Light` and `Dark` ResourceDictionaries only; our custom brushes (`BlarAccentBrush`, `UserBubbleBrush`, …) have no HighContrast variant. Ticketed. |
| 4 | **`TextBox` two-way binding needs `UpdateSourceTrigger=PropertyChanged`** | `TextBox.Text` uniquely defaults its trigger to `LostFocus`; the VM is stale until focus moves — and UIA `SendKeys` tests asserting immediately after typing will read stale VM state. | Not currently a defect — our composer uses `TextChanged`/`PreviewKeyDown` event handlers rather than two-way `x:Bind`. Keep this in mind before converting the composer to a bound VM property. |
| 5 | **`Converter={x:Null}` compiles but crashes `x:Bind` at first activation** | Generated code calls `LookupConverter("")` → null-deref (`NullReferenceException` / "Resource Dictionary Key can only be String-typed"). Omit the property instead. | Clean — no `Converter={x:Null}` in our XAML. Recorded so nobody adds one. |
| 6 | **WinUI 3 has NO `DataGrid` and NO `SizeToContent`** | Cross-framework instinct (WPF `DataGrid`, `SizeToContent="WidthAndHeight"`) silently doesn't exist. The Community Toolkit `DataGrid`'s columns also can't use `x:Bind`. | N/A today (no tabular grid in our UI). Documented so a future "add a table" task reaches for `ListView` + `Grid` `ItemTemplate` + header `Grid`, not the Toolkit `DataGrid`. |

## Patterns worth preferring (that we already mostly follow)

- **`x:Bind` static functions beat `IValueConverter`** for simple transforms: a `public static Visibility BoolToVisibility(bool)` on the page, called as `{x:Bind local:MainPage.BoolToVisibility(Vm.IsLoading), Mode=OneWay}`, is compile-checked and cheaper than a converter resource.
- **Never *replace* an `ObservableCollection<T>`** — `.Clear()` + re-add. This is also *why* a `OneTime` binding to an `ObservableCollection` `ItemsSource` is correct: the collection instance is stable and raises its own change notifications. (Our `Sessions`/`Messages` bindings rely on this — landmine #2's ItemsSource cases are only safe as long as this rule holds.)
- **Batch `DispatcherQueue.TryEnqueue`** — one enqueue that does `Clear()` + a `foreach` add, never one enqueue per item.
- **`ThemeShadow` elevations** by surface type: 16 tooltips, 32 flyouts/popups, 128 dialogs; non-popup casters need their target surfaces in `ThemeShadow.Receivers` or the shadow looks clipped.
- **Acrylic `BackgroundSizing`** already defaults to `InnerBorderEdge` (correct); the hazard is *changing* it to `OuterBorderEdge` on a bordered acrylic surface, which makes the material bleed past the stroke.

## Things we already do right (recorded so a review doesn't re-flag them)

- **100% `x:Bind`, zero `{Binding}`** across all 54 XAML bindings — compiled, type-safe.
- **No UI-thread blocking** — no `.Result` / `.Wait()` / `.GetAwaiter().GetResult()` in the C#.
- **No `ScrollViewer`-wrapping-a-collection** anti-pattern — the two `ScrollViewer.*` hits are attached properties on `TextBox`es, which is fine.
- **Proper `ThemeDictionaries` structure** with semantically-named brushes (by purpose, not hue) — only the HighContrast tier (#3) is missing.
- **The window IS sized** in the constructor (the DPI correctness of that sizing is #1, a separate issue).

## Globalization posture note (not a defect, a decision)

The skill assumes localization is in scope (`x:Uid` + `.resw` + `ResourceLoader` + `CultureInfo.CurrentCulture`).
BlarAI is a single-operator English-honoring system (see #939, English-honoring deferral confirmed). We are
**not** retrofitting `x:Uid`/`.resw` now — recording the pattern so that *if* localization is ever scoped, the
approach is known, rather than treating its absence as a defect a code review should flag.
