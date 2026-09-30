# Telegram UX review

Reviewed 2026-09-30. Scope: the family shopping bot's chat interface. This is a review of documented interaction patterns, not a ranking of the best bots or a hands-on audit of competitors.

## First-party evidence

- Telegram recommends inline buttons for navigation and settings because they do not add user messages to the chat. Updating the existing keyboard/message is described as smoother than sending and deleting messages. Reply keyboards are useful for frequently offered actions; an input placeholder can explain the expected entry. `/start` and `/help` are standard entry points, and the command menu makes commands discoverable. Official examples include `@gif`, `@wiki` and the demo `@DurgerKingBot`; they illustrate context-specific actions rather than evidence of market leadership. [Telegram Bot Features](https://core.telegram.org/bots/features#inline-keyboards)
- Every callback should receive `answerCallbackQuery`, even with no text, otherwise Telegram keeps showing a progress indicator. `ForceReply` is documented for guided input; Telegram's poll-bot example explains one question at a time rather than requiring command syntax. [Bot API: CallbackQuery and ForceReply](https://core.telegram.org/bots/api#callbackquery)
- Skeddy documents plain-language input, then confirmation and relevant follow-up actions such as snooze or completion. Its more complex scheduling lives in a Mini App. For this small shopping bot, the useful pattern is quick chat entry plus actions attached to the result; a Mini App is not required to adopt it. These are provider descriptions, not independently verified usability results. [Skeddy](https://skeddy.me/)

## Recommendations for this bot

These are design judgments inferred from the sources and the family's workflow.

| Priority | Change | Reason / acceptance check |
| --- | --- | --- |
| 1 | Route voice through the current input state | If the prompt asks for a product note, voice must edit that note rather than create shopping items. Name the product in the prompt and show the recognized note for confirmation. |
| 1 | Offer visible Cancel during every pending input | Text and voice entry must have a clear exit. Main-menu navigation should leave the pending mode so the next voice message is not unexpectedly saved as a note. |
| 1 | Update the list after a purchase in the same message | Repeated purchases should not create repeated list messages. A short callback acknowledgement and an Undo affordance provide feedback. |
| 1 | Use recognizable product-card actions | Prefer “Нотатка”, “Фото”, “Категорія”, “Куплено”, “До списку” over unexplained emoji-only actions. Keep destructive or committing actions distinct from viewing a card. |
| 2 | Keep a small stable home keyboard | Primary “Список”; secondary “Каталог” and “Історія”; contextual add/edit actions stay inline. Help should show one text example and how to use voice. |
| 2 | Give empty screens a next action | An empty list should explain that it is shared and offer “Додати товари”; no dead-end “empty” response. |
| 2 | Make catalog/history pagination predictable | Show page number, previous/next only when available, and a route back to the list. Preserve pagination context when reopening a card where practical. |
| 2 | Remove completed draft controls | After confirming or cancelling a draft, replace its controls with status so old buttons cannot look actionable. Double taps should give “Вже додано” rather than create duplicates. |

## Review limits and practical verification

No competitor bots were messaged and no family data was sent externally. Sources describe features and examples, not measurable task-completion improvements. Verify the implementation on a real phone with: text draft confirmation; note by voice; cancel followed by ordinary voice shopping input; three purchases without repeated lists; undo; both family members viewing the same remaining items; photo card back navigation; catalog pagination; stale buttons after confirmation. Preserve the existing shared-list model and batched partner notifications.

## Implemented in this iteration

- Product-name buttons open cards; distinct “Куплено” buttons commit purchases.
- Cards, category selection and catalog pagination edit their current message and provide a route back. List-view tracking is removed when a list becomes a card, so background updates cannot overwrite that card.
- Completed/cancelled drafts replace their confirmation controls with a result.
- Note prompts name the product, accept Ukrainian voice or text, and offer Cancel. Main menu navigation leaves note mode.
- One own-purchase feedback message is updated with Undo for the most recent purchase. Partner batching remains.
- Empty list includes an Add action; catalog includes page numbers; reply keyboard includes an input hint.

Verified with 12 automated tests, including shared purchase/undo, panel tracking, retiring draft controls, note navigation, voice notes and cancellation. Actual phone layout and usability still need family testing. No new runtime AI or paid service was added.
