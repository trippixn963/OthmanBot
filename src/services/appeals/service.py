"""
OthmanBot - Appeal Service
==========================

Main appeal service class that orchestrates appeal operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.services.appeals.embeds import (
    post_appeal_to_case_thread,
    update_appeal_embed_status,
)
from src.services.appeals.actions import undo_action
from src.services.appeals.notifications import send_appeal_result_dm

if TYPE_CHECKING:
    from src.bot import OthmanBot


class AppealService:
    """
    Service for handling appeal operations.

    Coordinates between:
    - Database (appeal records)
    - Case log service (posting to case threads)
    - User notifications (DMs)
    - Action reversal (allow/open)
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the appeal service.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot

    @property
    def db(self):
        """Get database from debates_service."""
        return self.bot.debates_service.db if self.bot.debates_service else None

    async def submit_appeal(
        self,
        user: Union[discord.User, discord.Member],
        action_type: str,
        action_id: int,
        reason: str,
        additional_context: Optional[str] = None,
    ) -> dict:
        """
        Submit a new appeal.

        Args:
            user: The user submitting the appeal
            action_type: Type of action being appealed ('disallow' or 'close')
            action_id: ID of the action (ban row ID or thread ID)
            reason: User's reason for the appeal
            additional_context: Optional additional context

        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        logger.info("Processing Appeal Submission", [
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Action Type", action_type),
            ("Action ID", str(action_id)),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        # Check if appeal already exists
        if await self.db.has_appeal_async(user.id, action_type, action_id):
            return {
                "success": False,
                "error": "You have already submitted an appeal for this action."
            }

        # Create the appeal
        appeal_id = await self.db.create_appeal_async(
            user_id=user.id,
            action_type=action_type,
            action_id=action_id,
            reason=reason,
            additional_context=additional_context,
        )

        if not appeal_id:
            return {
                "success": False,
                "error": "You have already submitted an appeal for this action."
            }

        # Post to case thread
        try:
            await post_appeal_to_case_thread(
                bot=self.bot,
                appeal_id=appeal_id,
                user=user,
                action_type=action_type,
                action_id=action_id,
                reason=reason,
                additional_context=additional_context,
            )
        except Exception as e:
            logger.error("Failed to post appeal to case thread", [
                ("Appeal ID", str(appeal_id)),
                ("Error", str(e)),
            ])

        logger.success("📝 Appeal Submitted", [
            ("Appeal ID", str(appeal_id)),
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Action Type", action_type),
            ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
        ])

        return {"success": True, "appeal_id": appeal_id}

    async def approve_appeal(
        self,
        appeal_id: int,
        reviewed_by: Union[discord.User, discord.Member],
    ) -> dict:
        """
        Approve an appeal and undo the action.

        Args:
            appeal_id: The appeal ID
            reviewed_by: The moderator who approved

        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        logger.info("Processing Appeal Approval", [
            ("Appeal ID", str(appeal_id)),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("ID", str(reviewed_by.id)),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        appeal = await self.db.get_appeal_async(appeal_id)
        if not appeal:
            return {"success": False, "error": "Appeal not found."}

        if appeal["status"] != "pending":
            return {"success": False, "error": f"Appeal already {appeal['status']}."}

        # Update status
        if not await self.db.update_appeal_status_async(appeal_id, "approved", reviewed_by.id):
            return {"success": False, "error": "Failed to update appeal status."}

        # Undo the action
        undo_success = await undo_action(
            bot=self.bot,
            user_id=appeal["user_id"],
            action_type=appeal["action_type"],
            action_id=appeal["action_id"],
            reviewed_by=reviewed_by,
        )

        if not undo_success:
            logger.warning("Appeal approved but action could not be undone", [
                ("Appeal ID", str(appeal_id)),
                ("Action Type", appeal["action_type"]),
            ])

        # Notify user
        await send_appeal_result_dm(
            bot=self.bot,
            user_id=appeal["user_id"],
            action_type=appeal["action_type"],
            approved=True,
            reviewed_by=reviewed_by,
            appeal_id=appeal_id,
        )

        logger.success("✅ Appeal Approved", [
            ("Appeal ID", str(appeal_id)),
            ("ID", str(appeal["user_id"])),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("Reviewer ID", str(reviewed_by.id)),
            ("Action Undone", str(undo_success)),
        ])

        # Update the appeal embed in case thread
        await update_appeal_embed_status(
            bot=self.bot,
            appeal_id=appeal_id,
            decision="approved",
            reviewed_by=reviewed_by,
        )

        return {"success": True}

    async def deny_appeal(
        self,
        appeal_id: int,
        reviewed_by: Union[discord.User, discord.Member],
        denial_reason: Optional[str] = None,
    ) -> dict:
        """
        Deny an appeal.

        Args:
            appeal_id: The appeal ID
            reviewed_by: The moderator who denied
            denial_reason: Optional reason for denial

        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        logger.info("Processing Appeal Denial", [
            ("Appeal ID", str(appeal_id)),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("ID", str(reviewed_by.id)),
            ("Denial Reason", denial_reason[:50] + "..." if denial_reason and len(denial_reason) > 50 else denial_reason or "None"),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        appeal = await self.db.get_appeal_async(appeal_id)
        if not appeal:
            return {"success": False, "error": "Appeal not found."}

        if appeal["status"] != "pending":
            return {"success": False, "error": f"Appeal already {appeal['status']}."}

        # Update status with denial reason
        if not await self.db.update_appeal_status_async(appeal_id, "denied", reviewed_by.id, denial_reason):
            return {"success": False, "error": "Failed to update appeal status."}

        # Notify user
        await send_appeal_result_dm(
            bot=self.bot,
            user_id=appeal["user_id"],
            action_type=appeal["action_type"],
            approved=False,
            reviewed_by=reviewed_by,
            appeal_id=appeal_id,
            denial_reason=denial_reason,
        )

        logger.warning("❌ Appeal Denied", [
            ("Appeal ID", str(appeal_id)),
            ("ID", str(appeal["user_id"])),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("Reviewer ID", str(reviewed_by.id)),
            ("Reason", denial_reason[:50] + "..." if denial_reason and len(denial_reason) > 50 else denial_reason or "None"),
        ])

        # Update the appeal embed in case thread
        await update_appeal_embed_status(
            bot=self.bot,
            appeal_id=appeal_id,
            decision="denied",
            reviewed_by=reviewed_by,
            denial_reason=denial_reason,
        )

        return {"success": True}


__all__ = ["AppealService"]
