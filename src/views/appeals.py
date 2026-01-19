"""
OthmanBot - Appeal Views and Modals
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

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import can_review_appeals, has_debates_management_role, EmbedColors
from src.core.emojis import APPEAL_EMOJI
from src.utils import sanitize_input

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
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
            logger.error("Appeal Service Not Initialized", [
                ("Context", "Appeal modal submission"),
            ])
            await interaction.followup.send(
                "The appeal system is currently unavailable. Please try again later.",
                ephemeral=True
            )
            return

        # Sanitize inputs
        sanitized_reason = sanitize_input(str(self.reason), max_length=REASON_MAX_LENGTH)
        sanitized_context = sanitize_input(
            str(self.additional_context) if self.additional_context.value else None,
            max_length=CONTEXT_MAX_LENGTH
        )

        # Validate reason is not empty after sanitization
        if not sanitized_reason:
            await interaction.followup.send(
                "Please provide a valid reason for your appeal.",
                ephemeral=True
            )
            return

        # Submit the appeal
        result = await self.bot.appeal_service.submit_appeal(
            user=interaction.user,
            action_type=self.action_type,
            action_id=self.action_id,
            reason=sanitized_reason,
            additional_context=sanitized_context,
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
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
        except discord.HTTPException as e:
            logger.debug("Appeal Error Response Failed", [
                ("Error", str(e)[:50]),
            ])


# =============================================================================
# Deny Reason Modal
# =============================================================================

DENIAL_REASON_MAX_LENGTH = 500


class DenyReasonModal(discord.ui.Modal):
    """
    Modal for moderators to provide a reason when denying an appeal.
    """

    denial_reason = discord.ui.TextInput(
        label="Why is this appeal being denied?",
        style=discord.TextStyle.paragraph,
        placeholder="Provide a reason for the denial...",
        required=True,
        max_length=DENIAL_REASON_MAX_LENGTH,
    )

    def __init__(
        self,
        appeal_id: int,
        bot: "OthmanBot",
        original_message: Optional[discord.Message] = None,
    ) -> None:
        """
        Initialize the denial reason modal.

        Args:
            appeal_id: The appeal ID being denied
            bot: The OthmanBot instance
            original_message: The original message with review buttons (to disable them)
        """
        super().__init__(title="Deny Appeal")
        self.appeal_id = appeal_id
        self.bot = bot
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.info("Deny Reason Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Appeal ID", str(self.appeal_id)),
            ("Reason Length", str(len(self.denial_reason.value))),
        ])

        # Defer while processing
        await interaction.response.defer(ephemeral=True)

        # Get appeal service
        if not self.bot.appeal_service:
            logger.error("Appeal Service Not Initialized", [
                ("Context", "Deny reason modal submission"),
            ])
            await interaction.followup.send(
                "The appeal system is currently unavailable.",
                ephemeral=True
            )
            return

        # Sanitize denial reason
        sanitized_reason = sanitize_input(self.denial_reason.value, max_length=DENIAL_REASON_MAX_LENGTH)
        if not sanitized_reason:
            await interaction.followup.send(
                "Please provide a valid reason for denying the appeal.",
                ephemeral=True
            )
            return

        # Process the denial with reason
        result = await self.bot.appeal_service.deny_appeal(
            appeal_id=self.appeal_id,
            reviewed_by=interaction.user,
            denial_reason=sanitized_reason,
        )

        if result["success"]:
            # Disable buttons on the message
            try:
                if self.original_message:
                    view = discord.ui.View(timeout=None)
                    for comp_row in self.original_message.components:
                        for child in comp_row.children:
                            button = discord.ui.Button(
                                style=discord.ButtonStyle.secondary,
                                label=child.label,
                                emoji=child.emoji,
                                disabled=True,
                                custom_id=child.custom_id,
                            )
                            view.add_item(button)
                    await self.original_message.edit(view=view)
            except Exception as e:
                logger.warning("Failed to disable review buttons", [
                    ("Error", str(e)),
                ])

            await interaction.followup.send(
                "Appeal denied successfully. The user has been notified with your reason.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                result.get("error", "Failed to deny appeal."),
                ephemeral=True
            )


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
            style=discord.ButtonStyle.secondary,
            label="Appeal",
            emoji=discord.PartialEmoji.from_str(APPEAL_EMOJI),
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

        # Get bot instance for webhook logging
        bot: "OthmanBot" = interaction.client  # type: ignore

        # Verify user is the one who should appeal FIRST (before logging)
        if interaction.user.id != expected_user_id:
            logger.warning("⛔ Appeal Button Rejected - Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
                ("Expected User ID", str(expected_user_id)),
                ("Action Type", action_type),
                ("Source", source),
            ])

            await interaction.response.send_message(
                "You cannot submit an appeal for another user.",
                ephemeral=True
            )
            return

        logger.info("📝 Appeal Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Action Type", action_type),
            ("Action ID", str(action_id)),
            ("Source", source),
        ])

        # Check if appeal already exists
        if bot.debates_service and bot.debates_service.db:
            has_appeal = await asyncio.to_thread(
                bot.debates_service.db.has_appeal,
                interaction.user.id,
                action_type,
                action_id
            )
            if has_appeal:
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
        try:
            await interaction.response.send_modal(modal)
        except discord.HTTPException as e:
            # Handle case where interaction was already acknowledged
            # (e.g., user dismissed modal and clicked again quickly)
            if e.code == 40060:  # Interaction has already been acknowledged
                logger.debug("Appeal modal send failed - interaction already acknowledged")
                # Try to send followup instead
                try:
                    await interaction.followup.send(
                        "Please try clicking the Appeal button again.",
                        ephemeral=True
                    )
                except discord.HTTPException as followup_err:
                    logger.debug("Appeal Modal Followup Also Failed", [
                        ("Original Error Code", str(e.code)),
                        ("Followup Error", str(followup_err)[:50]),
                    ])
            else:
                raise


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
            info_id = f"appeal_review:{appeal_id}:info"
        else:
            # Generic pattern for registration
            approve_id = "appeal_review:0:approve"
            deny_id = "appeal_review:0:deny"
            info_id = "appeal_review:0:info"

        self.add_item(ApproveButton(custom_id=approve_id))
        self.add_item(DenyButton(custom_id=deny_id))
        self.add_item(MoreInfoButton(custom_id=info_id))


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


class MoreInfoButton(discord.ui.Button):
    """More Info button - shows ban details to moderators."""

    def __init__(self, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="More Info",
            emoji="\u2139\ufe0f",  # info emoji
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle more info button click."""
        # This is handled by on_interaction for persistence
        pass


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
        ("Moderator", f"{interaction.user.name} ({interaction.user.display_name})"),
        ("ID", str(interaction.user.id)),
        ("Appeal ID", str(appeal_id)),
        ("Action", action),
    ])

    # Check if user can review appeals
    if not can_review_appeals(interaction.user):
        logger.warning("Appeal Review Denied - No Permission", [
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Appeal ID", str(appeal_id)),
        ])
        await interaction.response.send_message(
            "You don't have permission to review appeals.",
            ephemeral=True
        )
        return

    # Defer while processing
    await interaction.response.defer(ephemeral=True)

    # Get bot instance
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Get appeal service
    if not bot.appeal_service:
        logger.error("Appeal Service Not Initialized", [
            ("Context", "Review button handler"),
        ])
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
        ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
        ("ID", str(interaction.user.id)),
        ("Action Type", action_type),
        ("Action ID", str(action_id)),
        ("Expected User ID", str(expected_user_id)),
        ("Source", source),
    ])

    # Get bot instance
    from src.bot import OthmanBot
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Verify user is the one who should appeal
    if interaction.user.id != expected_user_id:
        logger.warning("Appeal Button Rejected - Wrong User", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Expected User ID", str(expected_user_id)),
            ("Action Type", action_type),
        ])
        await interaction.response.send_message(
            "You cannot submit an appeal for another user.",
            ephemeral=True
        )
        return

    # Check if appeal already exists
    if bot.debates_service and bot.debates_service.db:
        has_appeal = await asyncio.to_thread(
            bot.debates_service.db.has_appeal,
            interaction.user.id,
            action_type,
            action_id
        )
        if has_appeal:
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
        ("Moderator", f"{interaction.user.name} ({interaction.user.display_name})"),
        ("ID", str(interaction.user.id)),
        ("Appeal ID", str(appeal_id)),
        ("Action", action),
    ])

    # Check if user can review appeals
    if not can_review_appeals(interaction.user):
        logger.warning("Appeal Review Denied - No Permission", [
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Appeal ID", str(appeal_id)),
        ])
        await interaction.response.send_message(
            "You don't have permission to review appeals.",
            ephemeral=True
        )
        return

    # Get bot instance
    from src.bot import OthmanBot
    bot: "OthmanBot" = interaction.client  # type: ignore

    # For deny action, show modal to collect reason (don't defer yet)
    if action == "deny":
        modal = DenyReasonModal(
            appeal_id=appeal_id,
            bot=bot,
            original_message=interaction.message,
        )
        await interaction.response.send_modal(modal)
        return

    # Defer while processing approve
    await interaction.response.defer(ephemeral=True)

    # Get appeal service
    if not bot.appeal_service:
        logger.error("Appeal Service Not Initialized", [
            ("Context", "Review button v2 handler"),
        ])
        await interaction.followup.send(
            "The appeal system is currently unavailable.",
            ephemeral=True
        )
        return

    # Process approve
    result = await bot.appeal_service.approve_appeal(
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
            "Appeal approved successfully. The user has been notified.",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            result.get("error", "Failed to approve appeal."),
            ephemeral=True
        )


async def handle_info_button_interaction(
    interaction: discord.Interaction,
    custom_id: str
) -> None:
    """
    Handle "More Info" button click from on_interaction.

    Shows moderators detailed info about the user and their ban.
    """
    # Parse custom_id: appeal_review:{appeal_id}:info
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "appeal_review" or parts[2] != "info":
        logger.error("Invalid Info Button Custom ID", [
            ("Custom ID", custom_id),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    _, appeal_id_str, _ = parts

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
        logger.error("Invalid Appeal ID in Info Button", [
            ("Appeal ID", appeal_id_str),
        ])
        await interaction.response.send_message(
            "This button is invalid.",
            ephemeral=True
        )
        return

    logger.info("More Info Button Clicked", [
        ("Moderator", f"{interaction.user.name} ({interaction.user.display_name})"),
        ("ID", str(interaction.user.id)),
        ("Appeal ID", str(appeal_id)),
    ])

    # Check if user has Debates Management role
    if not has_debates_management_role(interaction.user):
        logger.warning("More Info Denied - Missing Role", [
            ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Appeal ID", str(appeal_id)),
        ])
        await interaction.response.send_message(
            "You don't have permission to view this information.",
            ephemeral=True
        )
        return

    # Defer while fetching info
    await interaction.response.defer(ephemeral=True)

    # Get bot instance
    from src.bot import OthmanBot
    bot: "OthmanBot" = interaction.client  # type: ignore

    # Get appeal data
    if not bot.debates_service or not bot.debates_service.db:
        await interaction.followup.send(
            "The database is currently unavailable.",
            ephemeral=True
        )
        return

    appeal = await asyncio.to_thread(bot.debates_service.db.get_appeal, appeal_id)
    if not appeal:
        await interaction.followup.send(
            "This appeal was not found in the database.",
            ephemeral=True
        )
        return

    user_id = appeal["user_id"]
    action_type = appeal["action_type"]
    action_id = appeal["action_id"]

    # Build detailed info embed
    embed = discord.Embed(
        title="📋 Appeal Details",
        color=EmbedColors.APPEAL_PENDING,
    )

    # Get user info
    try:
        user = await bot.fetch_user(user_id)
        embed.add_field(
            name="User",
            value=f"{user.mention} ({user.name})\nID: `{user_id}`",
            inline=True
        )
        embed.set_thumbnail(url=user.display_avatar.url)
    except Exception:
        embed.add_field(
            name="User",
            value=f"ID: `{user_id}`\n(Could not fetch user)",
            inline=True
        )

    embed.add_field(
        name="Action Type",
        value=ACTION_TYPE_LABELS.get(action_type, action_type),
        inline=True
    )

    # Get action-specific details
    if action_type == "disallow":
        # Get ban details from ban_history (uses appeal's created_at to find the correct ban)
        appeal_created_at = appeal.get("created_at")
        ban = None
        if appeal_created_at:
            ban = await asyncio.to_thread(bot.debates_service.db.get_ban_history_at_time, user_id, appeal_created_at)
        if not ban:
            # Fallback to current bans if history lookup fails
            bans = await asyncio.to_thread(bot.debates_service.db.get_user_bans, user_id)
            if bans:
                ban = bans[0]

        if ban:

            # Get moderator who banned
            banned_by_id = ban.get("banned_by")
            if banned_by_id:
                try:
                    banned_by = await bot.fetch_user(banned_by_id)
                    embed.add_field(
                        name="Banned By",
                        value=f"{banned_by.mention} ({banned_by.name})",
                        inline=True
                    )
                except Exception:
                    embed.add_field(
                        name="Banned By",
                        value=f"ID: `{banned_by_id}`",
                        inline=True
                    )

            # Get ban reason
            ban_reason = ban.get("reason") or "No reason provided"
            embed.add_field(
                name="Ban Reason",
                value=ban_reason[:1024],  # Discord limit
                inline=False
            )

            # Get thread if specific thread ban
            thread_id = ban.get("thread_id")
            if thread_id:
                try:
                    thread = bot.get_channel(thread_id)
                    if thread:
                        embed.add_field(
                            name="Banned From Thread",
                            value=f"{thread.mention}\n({thread.name})",
                            inline=True
                        )
                    else:
                        embed.add_field(
                            name="Banned From Thread",
                            value=f"ID: `{thread_id}` (deleted or inaccessible)",
                            inline=True
                        )
                except Exception:
                    embed.add_field(
                        name="Banned From Thread",
                        value=f"ID: `{thread_id}`",
                        inline=True
                    )
            else:
                embed.add_field(
                    name="Ban Scope",
                    value="All Debates (Global)",
                    inline=True
                )

            # Get ban date
            created_at = ban.get("created_at")
            if created_at:
                embed.add_field(
                    name="Banned On",
                    value=f"<t:{int(datetime.fromisoformat(created_at).timestamp())}:F>",
                    inline=True
                )

            # Get expiry
            expires_at = ban.get("expires_at")
            if expires_at:
                embed.add_field(
                    name="Expires",
                    value=f"<t:{int(datetime.fromisoformat(expires_at).timestamp())}:R>",
                    inline=True
                )
            else:
                embed.add_field(
                    name="Duration",
                    value="Permanent",
                    inline=True
                )
        else:
            embed.add_field(
                name="Ban Status",
                value="No active ban found (may have been lifted)",
                inline=False
            )

    elif action_type == "close":
        # Get thread info
        thread_id = action_id
        try:
            thread = bot.get_channel(thread_id)
            if thread:
                embed.add_field(
                    name="Closed Thread",
                    value=f"{thread.mention}\n({thread.name})",
                    inline=True
                )
            else:
                embed.add_field(
                    name="Closed Thread",
                    value=f"ID: `{thread_id}` (deleted or inaccessible)",
                    inline=True
                )
        except Exception:
            embed.add_field(
                name="Closed Thread",
                value=f"ID: `{thread_id}`",
                inline=True
            )

    # Add appeal info
    appeal_created = appeal.get("created_at")
    if appeal_created:
        try:
            ts = int(datetime.fromisoformat(appeal_created).timestamp())
            embed.add_field(
                name="Appeal Submitted",
                value=f"<t:{ts}:F> (<t:{ts}:R>)",
                inline=False
            )
        except Exception:
            embed.add_field(
                name="Appeal Submitted",
                value=appeal_created,
                inline=False
            )

    embed.set_footer(text=f"Appeal #{appeal_id}")

    await interaction.followup.send(embed=embed, ephemeral=True)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "AppealModal",
    "DenyReasonModal",
    "AppealButtonView",
    "AppealReviewView",
    "ACTION_TYPE_LABELS",
    "handle_appeal_button_interaction",
    "handle_review_button_interaction",
    "handle_info_button_interaction",
]
