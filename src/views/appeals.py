"""
Othman Discord Bot - Appeal Views and Modals
=============================================

Discord UI components for the appeal system.

Components:
- AppealModal: Modal for users to submit appeals
- AppealButtonView: Persistent view with appeal button (for DMs/embeds)
- AppealReviewView: Persistent view with Approve/Deny buttons (for case thread)

Custom ID Formats:
- Appeal button: appeal:{action_type}:{action_id}:{user_id}
- Review button: appeal_review:{appeal_id}:{action}

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import has_debates_management_role

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Max lengths for modal inputs
REASON_MAX_LENGTH = 500
CONTEXT_MAX_LENGTH = 300

# Action type labels for display
ACTION_TYPE_LABELS = {
    "disallow": "Disallowed from Debates",
    "close": "Debate Thread Closed",
}


# =============================================================================
# Appeal Modal
# =============================================================================

class AppealModal(discord.ui.Modal):
    """
    Modal for users to submit an appeal.

    Collects:
    - reason: Why the action should be reversed (required)
    - additional_context: Any additional context (optional)
    """

    reason = discord.ui.TextInput(
        label="Why should this be reversed?",
        style=discord.TextStyle.paragraph,
        placeholder="Explain why you believe this action should be reversed...",
        required=True,
        max_length=REASON_MAX_LENGTH,
    )

    additional_context = discord.ui.TextInput(
        label="Additional context (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Any additional information you'd like to provide...",
        required=False,
        max_length=CONTEXT_MAX_LENGTH,
    )

    def __init__(
        self,
        action_type: str,
        action_id: int,
        user_id: int,
        bot: "OthmanBot",
    ) -> None:
        """
        Initialize the appeal modal.

        Args:
            action_type: Type of action being appealed ('disallow' or 'close')
            action_id: ID of the action (ban row ID or thread ID)
            user_id: Discord user ID of the appealing user
            bot: The OthmanBot instance
        """
        super().__init__(title="Submit Appeal")
        self.action_type = action_type
        self.action_id = action_id
        self.user_id = user_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.info("Appeal Modal Submitted", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Action Type", self.action_type),
            ("Action ID", str(self.action_id)),
        ])

        # Defer response while processing
        await interaction.response.defer(ephemeral=True)

        # Verify user matches
        if interaction.user.id != self.user_id:
            await interaction.followup.send(
                "You cannot submit an appeal on behalf of another user.",
                ephemeral=True
            )
            return

        # Get appeal service
        if not self.bot.appeal_service:
            logger.error("Appeal service not initialized")
            await interaction.followup.send(
                "The appeal system is currently unavailable. Please try again later.",
                ephemeral=True
            )
            return

        # Submit the appeal
        result = await self.bot.appeal_service.submit_appeal(
            user=interaction.user,
            action_type=self.action_type,
            action_id=self.action_id,
            reason=str(self.reason),
            additional_context=str(self.additional_context) if self.additional_context.value else None,
        )

        if result["success"]:
            await interaction.followup.send(
                "Your appeal has been submitted successfully. "
                "You will be notified when a moderator reviews it.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                result.get("error", "Failed to submit appeal. Please try again later."),
                ephemeral=True
            )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error("Appeal Modal Error", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Action Type", self.action_type),
            ("Error", str(error)),
        ])

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "An error occurred while submitting your appeal. Please try again.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "An error occurred while submitting your appeal. Please try again.",
                    ephemeral=True
                )
        except discord.HTTPException:
            pass


# =============================================================================
# Appeal Button View (Persistent)
# =============================================================================

class AppealButtonView(discord.ui.View):
    """
    Persistent view with an appeal button.

    Used in:
    - Ban notification DMs
    - Close embed in threads
    - Close notification DMs

    Custom ID format: appeal:{action_type}:{action_id}:{user_id}

    DESIGN: timeout=None makes this persistent across bot restarts.
    The custom_id contains all info needed to recreate state.
    """

    def __init__(
        self,
        action_type: Optional[str] = None,
        action_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> None:
        """
        Initialize the appeal button view.

        Args:
            action_type: Type of action ('disallow' or 'close'), None for generic
            action_id: ID of the action, None for generic
            user_id: User ID who can appeal, None for generic

        Note: When all params are None, this creates a generic view for
        persistent view registration. The actual values come from custom_id.
        """
        super().__init__(timeout=None)

        # Build custom_id
        if action_type and action_id and user_id:
            custom_id = f"appeal:{action_type}:{action_id}:{user_id}"
        else:
            # Generic pattern for registration
            custom_id = "appeal:generic:0:0"

        self.add_item(AppealButton(custom_id=custom_id))


class AppealButton(discord.ui.Button):
    """
    The appeal button component.

    Parses custom_id to get action details and shows appeal modal.
    """

    def __init__(self, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Appeal",
            emoji="\U0001f4dd",  # memo emoji
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle appeal button click."""
        # Parse custom_id: appeal:{action_type}:{action_id}:{user_id}
        parts = self.custom_id.split(":")
        if len(parts) != 4 or parts[0] != "appeal":
            logger.error("Invalid Appeal Button Custom ID", [
                ("Custom ID", self.custom_id),
            ])
            await interaction.response.send_message(
                "This appeal button is invalid.",
                ephemeral=True
            )
            return

        _, action_type, action_id_str, user_id_str = parts

        # Handle generic placeholder
        if action_type == "generic":
            await interaction.response.send_message(
                "This appeal button is no longer valid.",
                ephemeral=True
            )
            return

        try:
            action_id = int(action_id_str)
            expected_user_id = int(user_id_str)
        except ValueError:
            logger.error("Invalid Appeal Button IDs", [
                ("Action ID", action_id_str),
                ("User ID", user_id_str),
            ])
            await interaction.response.send_message(
                "This appeal button is invalid.",
                ephemeral=True
            )
            return

        # Determine source (DM or Thread/Channel)
        is_dm = interaction.guild is None
        source = "DM" if is_dm else f"#{interaction.channel.name if interaction.channel else 'Unknown'}"

        logger.info("Appeal Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Action Type", action_type),
            ("Action ID", str(action_id)),
            ("Expected User", str(expected_user_id)),
            ("Source", source),
        ])

        # Get bot instance for webhook logging
        bot: "OthmanBot" = interaction.client  # type: ignore

        # Log to webhook
        try:
            if bot.interaction_logger:
                await bot.interaction_logger.log_appeal_button_clicked(
                    user=interaction.user,
                    action_type=action_type,
                    action_id=action_id,
                    source=source,
                    is_dm=is_dm,
                )
        except Exception as e:
            logger.warning("Failed to log appeal button click to webhook", [
                ("Error", str(e)),
            ])

        # Verify user is the one who should appeal
        if interaction.user.id != expected_user_id:
            logger.warning("Appeal Button Rejected - Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(expected_user_id)),
                ("Action Type", action_type),
            ])
            await interaction.response.send_message(
                "You cannot submit an appeal for another user.",
                ephemeral=True
            )
            return

        # Check if appeal already exists
        if bot.debates_service and bot.debates_service.db:
            if bot.debates_service.db.has_appeal(
                user_id=interaction.user.id,
                action_type=action_type,
                action_id=action_id
            ):
                await interaction.response.send_message(
                    "You have already submitted an appeal for this action. "
                    "Please wait for a moderator to review it.",
                    ephemeral=True
                )
                return

        # Show the appeal modal
        modal = AppealModal(
            action_type=action_type,
            action_id=action_id,
            user_id=interaction.user.id,
            bot=bot,
        )
        await interaction.response.send_modal(modal)


# =============================================================================
# Appeal Review View (Persistent)
# =============================================================================

class AppealReviewView(discord.ui.View):
    """
    Persistent view with Approve/Deny buttons for moderators.

    Used in case log thread when appeal is submitted.

    Custom ID format: appeal_review:{appeal_id}:{action}

    DESIGN: timeout=None makes this persistent across bot restarts.
    """

    def __init__(self, appeal_id: Optional[int] = None) -> None:
        """
        Initialize the review view.

        Args:
            appeal_id: The appeal ID, None for generic registration
        """
        super().__init__(timeout=None)

        if appeal_id:
            approve_id = f"appeal_review:{appeal_id}:approve"
            deny_id = f"appeal_review:{appeal_id}:deny"
        else:
            # Generic pattern for registration
            approve_id = "appeal_review:0:approve"
            deny_id = "appeal_review:0:deny"

        self.add_item(ApproveButton(custom_id=approve_id))
        self.add_item(DenyButton(custom_id=deny_id))


class ApproveButton(discord.ui.Button):
    """Approve appeal button."""

    def __init__(self, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.success,
            label="Approve",
            emoji="\u2705",  # white check mark
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle approve button click."""
        await _handle_review_button(interaction, self.custom_id, "approve")


class DenyButton(discord.ui.Button):
    """Deny appeal button."""

    def __init__(self, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Deny",
            emoji="\u274c",  # cross mark
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle deny button click."""
        await _handle_review_button(interaction, self.custom_id, "deny")


async def _handle_review_button(
    interaction: discord.Interaction,
    custom_id: str,
    expected_action: str
) -> None:
    """
    Handle appeal review button click.

    Args:
        interaction: The Discord interaction
        custom_id: Button custom ID
        expected_action: Expected action ('approve' or 'deny')
    """
    # Parse custom_id: appeal_review:{appeal_id}:{action}
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "appeal_review":
        logger.error("Invalid Review Button Custom ID", [
            ("Custom ID", custom_id),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    _, appeal_id_str, action = parts

    # Handle generic placeholder
    if appeal_id_str == "0":
        await interaction.response.send_message(
            "This button is no longer valid.",
            ephemeral=True
        )
        return

    try:
        appeal_id = int(appeal_id_str)
    except ValueError:
        logger.error("Invalid Appeal ID in Review Button", [
            ("Appeal ID", appeal_id_str),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    logger.info("Appeal Review Button Clicked", [
        ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
        ("Appeal ID", str(appeal_id)),
        ("Action", action),
    ])

    # Check if user has Debates Management role
    if not has_debates_management_role(interaction.user):
        logger.warning("Appeal Review Denied - Missing Role", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Appeal ID", str(appeal_id)),
        ])
        await interaction.response.send_message(
            "You don't have permission to review appeals. "
            "Only users with the Debates Management role can approve or deny appeals.",
            ephemeral=True
        )
        return

    # Defer while processing
    await interaction.response.defer(ephemeral=True)

    # Get bot instance
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Get appeal service
    if not bot.appeal_service:
        logger.error("Appeal service not initialized")
        await interaction.followup.send(
            "The appeal system is currently unavailable.",
            ephemeral=True
        )
        return

    # Process the review
    if action == "approve":
        result = await bot.appeal_service.approve_appeal(
            appeal_id=appeal_id,
            reviewed_by=interaction.user,
        )
    else:
        result = await bot.appeal_service.deny_appeal(
            appeal_id=appeal_id,
            reviewed_by=interaction.user,
        )

    if result["success"]:
        # Disable buttons on the message
        try:
            if interaction.message:
                view = discord.ui.View(timeout=None)
                for child in interaction.message.components[0].children if interaction.message.components else []:
                    button = discord.ui.Button(
                        style=discord.ButtonStyle.secondary,
                        label=child.label,
                        emoji=child.emoji,
                        disabled=True,
                        custom_id=child.custom_id,
                    )
                    view.add_item(button)
                await interaction.message.edit(view=view)
        except Exception as e:
            logger.warning("Failed to disable review buttons", [
                ("Error", str(e)),
            ])

        await interaction.followup.send(
            f"Appeal {action}d successfully. The user has been notified.",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            result.get("error", f"Failed to {action} appeal."),
            ephemeral=True
        )


# =============================================================================
# Standalone Interaction Handlers (for on_interaction routing)
# =============================================================================

async def handle_appeal_button_interaction(
    interaction: discord.Interaction,
    custom_id: str
) -> None:
    """
    Handle appeal button click from on_interaction.

    This is called from bot.on_interaction for persistent button handling.
    """
    # Parse custom_id: appeal:{action_type}:{action_id}:{user_id}
    parts = custom_id.split(":")
    if len(parts) != 4 or parts[0] != "appeal":
        logger.error("Invalid Appeal Button Custom ID", [
            ("Custom ID", custom_id),
        ])
        await interaction.response.send_message(
            "This appeal button is invalid.",
            ephemeral=True
        )
        return

    _, action_type, action_id_str, user_id_str = parts

    # Handle generic placeholder
    if action_type == "generic":
        await interaction.response.send_message(
            "This appeal button is no longer valid.",
            ephemeral=True
        )
        return

    try:
        action_id = int(action_id_str)
        expected_user_id = int(user_id_str)
    except ValueError:
        logger.error("Invalid Appeal Button IDs", [
            ("Action ID", action_id_str),
            ("User ID", user_id_str),
        ])
        await interaction.response.send_message(
            "This appeal button is invalid.",
            ephemeral=True
        )
        return

    # Determine source (DM or Thread/Channel)
    is_dm = interaction.guild is None
    source = "DM" if is_dm else f"#{interaction.channel.name if interaction.channel else 'Unknown'}"

    logger.info("Appeal Button Clicked", [
        ("User", f"{interaction.user.name} ({interaction.user.id})"),
        ("Action Type", action_type),
        ("Action ID", str(action_id)),
        ("Expected User", str(expected_user_id)),
        ("Source", source),
    ])

    # Get bot instance for webhook logging
    from src.bot import OthmanBot
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Log to webhook
    try:
        if bot.interaction_logger:
            await bot.interaction_logger.log_appeal_button_clicked(
                user=interaction.user,
                action_type=action_type,
                action_id=action_id,
                source=source,
                is_dm=is_dm,
            )
    except Exception as e:
        logger.warning("Failed to log appeal button click to webhook", [
            ("Error", str(e)),
        ])

    # Verify user is the one who should appeal
    if interaction.user.id != expected_user_id:
        logger.warning("Appeal Button Rejected - Wrong User", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Expected User", str(expected_user_id)),
            ("Action Type", action_type),
        ])
        await interaction.response.send_message(
            "You cannot submit an appeal for another user.",
            ephemeral=True
        )
        return

    # Check if appeal already exists
    if bot.debates_service and bot.debates_service.db:
        if bot.debates_service.db.has_appeal(
            user_id=interaction.user.id,
            action_type=action_type,
            action_id=action_id
        ):
            await interaction.response.send_message(
                "You have already submitted an appeal for this action. "
                "Please wait for a moderator to review it.",
                ephemeral=True
            )
            return

    # Show the appeal modal
    modal = AppealModal(
        action_type=action_type,
        action_id=action_id,
        user_id=interaction.user.id,
        bot=bot,
    )
    await interaction.response.send_modal(modal)


async def handle_review_button_interaction(
    interaction: discord.Interaction,
    custom_id: str
) -> None:
    """
    Handle appeal review button click (Approve/Deny) from on_interaction.

    This is called from bot.on_interaction for persistent button handling.
    """
    # Parse custom_id: appeal_review:{appeal_id}:{action}
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "appeal_review":
        logger.error("Invalid Review Button Custom ID", [
            ("Custom ID", custom_id),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    _, appeal_id_str, action = parts

    # Handle generic placeholder
    if appeal_id_str == "0":
        await interaction.response.send_message(
            "This button is no longer valid.",
            ephemeral=True
        )
        return

    try:
        appeal_id = int(appeal_id_str)
    except ValueError:
        logger.error("Invalid Appeal ID in Review Button", [
            ("Appeal ID", appeal_id_str),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    logger.info("Appeal Review Button Clicked", [
        ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
        ("Appeal ID", str(appeal_id)),
        ("Action", action),
    ])

    # Check if user has Debates Management role
    if not has_debates_management_role(interaction.user):
        logger.warning("Appeal Review Denied - Missing Role", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Appeal ID", str(appeal_id)),
        ])
        await interaction.response.send_message(
            "You don't have permission to review appeals. "
            "Only users with the Debates Management role can approve or deny appeals.",
            ephemeral=True
        )
        return

    # Defer while processing
    await interaction.response.defer(ephemeral=True)

    # Get bot instance
    from src.bot import OthmanBot
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Get appeal service
    if not bot.appeal_service:
        logger.error("Appeal service not initialized")
        await interaction.followup.send(
            "The appeal system is currently unavailable.",
            ephemeral=True
        )
        return

    # Process the review
    if action == "approve":
        result = await bot.appeal_service.approve_appeal(
            appeal_id=appeal_id,
            reviewed_by=interaction.user,
        )
    else:
        result = await bot.appeal_service.deny_appeal(
            appeal_id=appeal_id,
            reviewed_by=interaction.user,
        )

    if result["success"]:
        # Disable buttons on the message
        try:
            if interaction.message:
                view = discord.ui.View(timeout=None)
                for child in interaction.message.components[0].children if interaction.message.components else []:
                    button = discord.ui.Button(
                        style=discord.ButtonStyle.secondary,
                        label=child.label,
                        emoji=child.emoji,
                        disabled=True,
                        custom_id=child.custom_id,
                    )
                    view.add_item(button)
                await interaction.message.edit(view=view)
        except Exception as e:
            logger.warning("Failed to disable review buttons", [
                ("Error", str(e)),
            ])

        await interaction.followup.send(
            f"Appeal {action}d successfully. The user has been notified.",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            result.get("error", f"Failed to {action} appeal."),
            ephemeral=True
        )


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "AppealModal",
    "AppealButtonView",
    "AppealReviewView",
    "ACTION_TYPE_LABELS",
    "handle_appeal_button_interaction",
    "handle_review_button_interaction",
]
