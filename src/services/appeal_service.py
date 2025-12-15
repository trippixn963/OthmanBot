"""
Othman Discord Bot - Appeal Service
====================================

Business logic for the appeal system.

Handles:
- Appeal submission (creates appeal, posts to case thread)
- Appeal approval (undoes action, notifies user)
- Appeal denial (notifies user)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import NY_TZ, DEBATES_FORUM_ID, EmbedColors, EmbedIcons, EMBED_FOOTER_TEXT, EMBED_NO_VALUE
from src.views.appeals import AppealReviewView, ACTION_TYPE_LABELS
from src.utils import edit_thread_with_retry, get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Embed colors - using centralized config
COLOR_APPEAL_SUBMITTED = EmbedColors.APPEAL_PENDING
COLOR_APPEAL_APPROVED = EmbedColors.APPEAL_APPROVED
COLOR_APPEAL_DENIED = EmbedColors.APPEAL_DENIED


# =============================================================================
# Appeal Service
# =============================================================================

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
            ("User", f"{user.name} ({user.id})"),
            ("Action Type", action_type),
            ("Action ID", str(action_id)),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        # Check if appeal already exists
        if self.db.has_appeal(user.id, action_type, action_id):
            return {
                "success": False,
                "error": "You have already submitted an appeal for this action."
            }

        # Create the appeal
        # Note: create_appeal() returns None if a duplicate is detected via UNIQUE constraint
        # This handles the race condition where two requests pass has_appeal() simultaneously
        appeal_id = self.db.create_appeal(
            user_id=user.id,
            action_type=action_type,
            action_id=action_id,
            reason=reason,
            additional_context=additional_context,
        )

        if not appeal_id:
            # Most likely a race condition duplicate - another request created it first
            return {
                "success": False,
                "error": "You have already submitted an appeal for this action."
            }

        # Post to case thread
        try:
            await self._post_appeal_to_case_thread(
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
            # Appeal is still created, just not posted to case thread

        logger.success("Appeal Submitted Successfully", [
            ("Appeal ID", str(appeal_id)),
            ("User", f"{user.name} ({user.id})"),
            ("Action Type", action_type),
        ])

        # Log to webhook
        try:
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_appeal_submitted(
                    user=user,
                    action_type=action_type,
                    action_id=action_id,
                    reason=reason,
                    appeal_id=appeal_id,
                )
        except Exception as e:
            logger.warning("Failed to log appeal submission to webhook", [
                ("Error", str(e)),
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
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        # Get the appeal
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return {"success": False, "error": "Appeal not found."}

        if appeal["status"] != "pending":
            return {"success": False, "error": f"Appeal already {appeal['status']}."}

        # Update status
        if not self.db.update_appeal_status(appeal_id, "approved", reviewed_by.id):
            return {"success": False, "error": "Failed to update appeal status."}

        # Undo the action
        undo_success = await self._undo_action(
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
        await self._send_appeal_result_dm(
            user_id=appeal["user_id"],
            action_type=appeal["action_type"],
            approved=True,
            reviewed_by=reviewed_by,
            appeal_id=appeal_id,
        )

        logger.success("Appeal Approved", [
            ("Appeal ID", str(appeal_id)),
            ("User ID", str(appeal["user_id"])),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
            ("Action Undone", str(undo_success)),
        ])

        # Log to webhook
        try:
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_appeal_reviewed(
                    appeal_id=appeal_id,
                    user_id=appeal["user_id"],
                    action_type=appeal["action_type"],
                    decision="approved",
                    reviewed_by=reviewed_by,
                )
        except Exception as e:
            logger.warning("Failed to log appeal approval to webhook", [
                ("Error", str(e)),
            ])

        # Update the appeal embed in case thread
        await self._update_appeal_embed_status(
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
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
            ("Denial Reason", denial_reason[:50] + "..." if denial_reason and len(denial_reason) > 50 else denial_reason or "None"),
        ])

        if not self.db:
            return {"success": False, "error": "Appeal system is unavailable."}

        # Get the appeal
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return {"success": False, "error": "Appeal not found."}

        if appeal["status"] != "pending":
            return {"success": False, "error": f"Appeal already {appeal['status']}."}

        # Update status with denial reason
        if not self.db.update_appeal_status(appeal_id, "denied", reviewed_by.id, denial_reason):
            return {"success": False, "error": "Failed to update appeal status."}

        # Notify user
        await self._send_appeal_result_dm(
            user_id=appeal["user_id"],
            action_type=appeal["action_type"],
            approved=False,
            reviewed_by=reviewed_by,
            appeal_id=appeal_id,
            denial_reason=denial_reason,
        )

        logger.info("Appeal Denied", [
            ("Appeal ID", str(appeal_id)),
            ("User ID", str(appeal["user_id"])),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
            ("Reason", denial_reason[:50] + "..." if denial_reason and len(denial_reason) > 50 else denial_reason or "None"),
        ])

        # Log to webhook
        try:
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_appeal_reviewed(
                    appeal_id=appeal_id,
                    user_id=appeal["user_id"],
                    action_type=appeal["action_type"],
                    decision="denied",
                    reviewed_by=reviewed_by,
                )
        except Exception as e:
            logger.warning("Failed to log appeal denial to webhook", [
                ("Error", str(e)),
            ])

        # Update the appeal embed in case thread
        await self._update_appeal_embed_status(
            appeal_id=appeal_id,
            decision="denied",
            reviewed_by=reviewed_by,
            denial_reason=denial_reason,
        )

        return {"success": True}

    async def _post_appeal_to_case_thread(
        self,
        appeal_id: int,
        user: Union[discord.User, discord.Member],
        action_type: str,
        action_id: int,
        reason: str,
        additional_context: Optional[str],
    ) -> None:
        """Post appeal embed to user's case thread."""
        if not self.bot.case_log_service:
            logger.warning("Case log service not available for appeal posting")
            return

        # Get or create case thread
        case = self.db.get_case_log(user.id)
        if not case:
            logger.info("No case thread exists for appeal user", [
                ("User ID", str(user.id)),
            ])
            return

        # Get the case thread
        case_thread = await self.bot.case_log_service._get_case_thread(case["thread_id"])
        if not case_thread:
            logger.warning("Could not find case thread for appeal", [
                ("Thread ID", str(case["thread_id"])),
            ])
            return

        # Get the original moderator who took the action
        action_by_id: Optional[int] = None
        if action_type == "disallow":
            # Get from ban_history - most recent ban for this user
            ban_history = self.db.get_user_ban_history(user.id, limit=1)
            if ban_history:
                action_by_id = ban_history[0].get("banned_by")
        elif action_type == "close":
            # Get from closure_history
            closure = self.db.get_closure_by_thread_id(action_id)
            if closure:
                action_by_id = closure.get("closed_by")

        # Build the appeal embed
        now = datetime.now(NY_TZ)
        action_label = ACTION_TYPE_LABELS.get(action_type, action_type.title())

        embed = discord.Embed(
            title="\U0001f4dd Appeal Submitted",
            color=COLOR_APPEAL_SUBMITTED,
            timestamp=now,
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(
            name="Action Being Appealed",
            value=action_label,
            inline=True,
        )

        # Add thread link if it's a close appeal
        if action_type == "close":
            embed.add_field(
                name="Thread",
                value=f"<#{action_id}>",
                inline=True,
            )

        # Add who took the original action
        if action_by_id:
            embed.add_field(
                name="Action By",
                value=f"<@{action_by_id}>",
                inline=True,
            )

        embed.add_field(
            name="Submitted",
            value=f"<t:{int(now.timestamp())}:R>",
            inline=True,
        )

        embed.add_field(
            name="Reason for Appeal",
            value=reason[:1024],
            inline=False,
        )

        if additional_context:
            embed.add_field(
                name="Additional Context",
                value=additional_context[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="Additional Context",
                value="_None provided_",
                inline=False,
            )

        embed.set_footer(
            text=f"Appeal #{appeal_id} | User can appeal once per action",
        )

        # Create review view with Approve/Deny buttons
        view = AppealReviewView(appeal_id=appeal_id)

        # Send to case thread
        message = await case_thread.send(embed=embed, view=view)

        # Store message ID so we can edit it when approved/denied
        if message and self.db:
            self.db.set_appeal_case_message_id(appeal_id, message.id)

        logger.info("Appeal Posted to Case Thread", [
            ("Appeal ID", str(appeal_id)),
            ("Case Thread ID", str(case["thread_id"])),
            ("Message ID", str(message.id) if message else "None"),
        ])

    async def _undo_action(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
        reviewed_by: Union[discord.User, discord.Member],
    ) -> bool:
        """
        Undo the moderation action.

        For disallow: Remove the ban
        For close: Reopen the thread

        Returns:
            True if successful, False otherwise
        """
        if action_type == "disallow":
            return await self._undo_disallow(user_id, reviewed_by)
        elif action_type == "close":
            return await self._undo_close(user_id, action_id, reviewed_by)
        else:
            logger.warning("Unknown action type for appeal undo", [
                ("Action Type", action_type),
            ])
            return False

    async def _undo_disallow(
        self,
        user_id: int,
        reviewed_by: Union[discord.User, discord.Member],
    ) -> bool:
        """Remove debate ban for user."""
        if not self.db:
            return False

        # Remove all bans for this user (appeals are for global disallows typically)
        success = self.db.remove_debate_ban(user_id=user_id, thread_id=None)

        if success:
            logger.info("Appeal: Disallow Undone", [
                ("User ID", str(user_id)),
                ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
            ])

            # Update ban_history to mark as removed via appeal
            try:
                self.db.update_ban_history_removal(
                    user_id=user_id,
                    removed_by=reviewed_by.id,
                    removal_reason="Appeal approved"
                )
            except Exception as e:
                logger.warning("Failed to update ban history for appeal", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])

            # Log to case thread
            try:
                if self.bot.case_log_service:
                    # Get user for display name
                    member = None
                    for guild in self.bot.guilds:
                        member = guild.get_member(user_id)
                        if member:
                            break

                    await self.bot.case_log_service.log_unban(
                        user_id=user_id,
                        unbanned_by=reviewed_by,
                        scope="all debates",
                        display_name=member.display_name if member else f"User {user_id}",
                        reason="Appeal approved",
                    )
            except Exception as e:
                logger.warning("Failed to log appeal unban to case system", [
                    ("Error", str(e)),
                ])

        return success

    async def _undo_close(
        self,
        user_id: int,
        thread_id: int,
        reviewed_by: Union[discord.User, discord.Member],
    ) -> bool:
        """Reopen a closed thread."""
        # Find the thread
        thread: Optional[discord.Thread] = None

        for guild in self.bot.guilds:
            try:
                thread = guild.get_thread(thread_id)
                if not thread:
                    # Try to fetch if not cached
                    thread = await guild.fetch_channel(thread_id)
            except (discord.NotFound, discord.Forbidden):
                continue

            if thread and isinstance(thread, discord.Thread):
                break

        if not thread:
            logger.warning("Appeal: Could not find thread to reopen", [
                ("Thread ID", str(thread_id)),
            ])
            return False

        # Verify it's in debates forum
        if thread.parent_id != DEBATES_FORUM_ID:
            logger.warning("Appeal: Thread not in debates forum", [
                ("Thread ID", str(thread_id)),
                ("Parent ID", str(thread.parent_id)),
            ])
            return False

        # Verify it's closed
        if not thread.name.startswith("[CLOSED]"):
            logger.info("Appeal: Thread already open", [
                ("Thread ID", str(thread_id)),
            ])
            return True  # Already open, consider success

        # Try to get original thread name from closure_history
        # This preserves the original debate number
        original_name = None
        original_num = None
        if self.db:
            closure_record = self.db.get_closure_by_thread_id(thread_id)
            if closure_record and closure_record.get("thread_name"):
                original_name = closure_record["thread_name"]
                # Extract original number from stored name (format: "13 | Title")
                num_match = re.match(r'^(\d+)\s*\|\s*(.+)$', original_name)
                if num_match:
                    original_num = int(num_match.group(1))
                    logger.info("Appeal: Found original thread number in history", [
                        ("Thread ID", str(thread_id)),
                        ("Original Number", str(original_num)),
                    ])

        # If we have the original name, use it directly
        if original_name and original_num:
            new_name = original_name
        else:
            # Fallback: extract title and get next number
            title = thread.name
            if title.startswith("[CLOSED] | "):
                title = title[11:]
            elif title.startswith("[CLOSED]"):
                title = title[8:].lstrip(" |")

            # Handle legacy format
            legacy_match = re.match(r'^\d+\s*\|\s*(.+)$', title)
            if legacy_match:
                title = legacy_match.group(1)

            # Get next debate number
            next_num = 1
            if self.db:
                next_num = self.db.get_next_debate_number()

            # Build new name
            new_name = f"{next_num} | {title}"

        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        # Reopen thread
        try:
            await edit_thread_with_retry(thread, name=new_name, archived=False, locked=False)
            logger.info("Appeal: Thread Reopened", [
                ("Thread ID", str(thread_id)),
                ("New Name", new_name),
            ])

            # Update closure_history to mark as reopened via appeal
            if self.db:
                try:
                    self.db.update_closure_history_reopened(
                        thread_id=thread_id,
                        reopened_by=reviewed_by.id
                    )
                except Exception as e:
                    logger.warning("Failed to update closure history for appeal", [
                        ("Thread ID", str(thread_id)),
                        ("Error", str(e)),
                    ])

            return True
        except Exception as e:
            logger.error("Appeal: Failed to reopen thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)),
            ])
            return False

    async def _send_appeal_result_dm(
        self,
        user_id: int,
        action_type: str,
        approved: bool,
        reviewed_by: Union[discord.User, discord.Member],
        appeal_id: Optional[int] = None,
        denial_reason: Optional[str] = None,
    ) -> bool:
        """Send DM to user with appeal result."""
        # Find the user
        user: Optional[discord.User] = None

        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            logger.warning("Appeal: Could not find user for DM", [
                ("User ID", str(user_id)),
            ])
            return False

        if not user:
            return False

        # Get developer avatar for footer
        developer_avatar_url = await get_developer_avatar(self.bot)

        action_label = ACTION_TYPE_LABELS.get(action_type, action_type.title())
        now = datetime.now(NY_TZ)

        if approved:
            embed = discord.Embed(
                title=f"{EmbedIcons.APPROVED} Appeal Approved",
                description=(
                    "Your appeal has been approved and the action has been reversed."
                ),
                color=COLOR_APPEAL_APPROVED,
                timestamp=now,
            )
            embed.set_thumbnail(url=reviewed_by.display_avatar.url)
            embed.add_field(
                name="Action Reversed",
                value=action_label,
                inline=True,
            )
            # What's Next for approved
            embed.add_field(
                name="What's Next?",
                value="You can now participate in debates again.",
                inline=False,
            )
        else:
            embed = discord.Embed(
                title=f"{EmbedIcons.DENIED} Appeal Denied",
                description=(
                    "Your appeal has been reviewed and denied."
                ),
                color=COLOR_APPEAL_DENIED,
                timestamp=now,
            )
            embed.set_thumbnail(url=reviewed_by.display_avatar.url)
            embed.add_field(
                name="Action",
                value=f"{action_label} remains",
                inline=True,
            )

        embed.add_field(
            name="Reviewed By",
            value=reviewed_by.display_name,
            inline=True,
        )
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True,
        )

        # Add appeal ID if provided
        if appeal_id:
            embed.add_field(
                name="Appeal ID",
                value=f"`#{appeal_id}`",
                inline=True,
            )

        # Add denial reason if provided
        if not approved and denial_reason:
            reason_display = denial_reason[:1000] + "..." if len(denial_reason) > 1000 else denial_reason
            embed.add_field(
                name="Reason",
                value=reason_display,
                inline=False,
            )

        embed.set_footer(
            text=EMBED_FOOTER_TEXT,
            icon_url=developer_avatar_url,
        )

        try:
            await user.send(embed=embed)
            logger.info("Appeal Result DM Sent", [
                ("User ID", str(user_id)),
                ("Approved", str(approved)),
            ])
            return True
        except discord.Forbidden:
            logger.warning("Appeal: Could not send DM - DMs disabled", [
                ("User ID", str(user_id)),
            ])
            return False
        except discord.HTTPException as e:
            logger.warning("Appeal: DM failed", [
                ("User ID", str(user_id)),
                ("Error", str(e)),
            ])
            return False

    async def _update_appeal_embed_status(
        self,
        appeal_id: int,
        decision: str,
        reviewed_by: Union[discord.User, discord.Member],
        denial_reason: Optional[str] = None,
    ) -> bool:
        """
        Edit the existing appeal embed in case thread to show the decision.

        Instead of sending a new message, this edits the original appeal embed
        to add an "Approved by @user" or "Denied by @user" field.

        Args:
            appeal_id: The appeal ID
            decision: Either "approved" or "denied"
            reviewed_by: The moderator who reviewed
            denial_reason: Optional reason for denial

        Returns:
            True if successful, False otherwise
        """
        if not self.db:
            return False

        # Get the appeal with case_message_id
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            logger.warning("Cannot update appeal embed - appeal not found", [
                ("Appeal ID", str(appeal_id)),
            ])
            return False

        case_message_id = appeal.get("case_message_id")
        if not case_message_id:
            logger.warning("Cannot update appeal embed - no case_message_id stored", [
                ("Appeal ID", str(appeal_id)),
            ])
            return False

        # Get the case thread
        if not self.bot.case_log_service:
            return False

        case = self.db.get_case_log(appeal["user_id"])
        if not case:
            return False

        case_thread = await self.bot.case_log_service._get_case_thread(case["thread_id"])
        if not case_thread:
            logger.warning("Cannot update appeal embed - case thread not found", [
                ("Thread ID", str(case["thread_id"])),
            ])
            return False

        try:
            # Fetch the message
            message = await case_thread.fetch_message(case_message_id)
            if not message or not message.embeds:
                logger.warning("Cannot update appeal embed - message has no embeds", [
                    ("Message ID", str(case_message_id)),
                ])
                return False

            # Get the existing embed and create a copy
            old_embed = message.embeds[0]
            now = datetime.now(NY_TZ)

            # Determine new color and title based on decision
            if decision == "approved":
                new_color = COLOR_APPEAL_APPROVED
                new_title = f"{EmbedIcons.APPROVED} Appeal Approved"
                decision_field_name = "Approved By"
                decision_field_value = f"<@{reviewed_by.id}>"
            else:
                new_color = COLOR_APPEAL_DENIED
                new_title = f"{EmbedIcons.DENIED} Appeal Denied"
                decision_field_name = "Denied By"
                decision_field_value = f"<@{reviewed_by.id}>"

            # Create new embed with updated info
            new_embed = discord.Embed(
                title=new_title,
                color=new_color,
                timestamp=old_embed.timestamp,
            )

            # Copy thumbnail
            if old_embed.thumbnail:
                new_embed.set_thumbnail(url=old_embed.thumbnail.url)

            # Copy existing fields (action, thread, submitted, reason, context)
            for field in old_embed.fields:
                new_embed.add_field(
                    name=field.name,
                    value=field.value,
                    inline=field.inline,
                )

            # Add review decision field
            new_embed.add_field(
                name=decision_field_name,
                value=decision_field_value,
                inline=True,
            )

            # Add review timestamp
            new_embed.add_field(
                name="Reviewed",
                value=f"<t:{int(now.timestamp())}:R>",
                inline=True,
            )

            # Add denial reason if provided
            if decision == "denied" and denial_reason:
                new_embed.add_field(
                    name="Denial Reason",
                    value=denial_reason[:1024],
                    inline=False,
                )

            # Update footer
            new_embed.set_footer(
                text=f"Appeal #{appeal_id} | {decision.title()}",
            )

            # Edit the message - remove the view (buttons) since it's been reviewed
            await message.edit(embed=new_embed, view=None)

            logger.info("Appeal Embed Updated", [
                ("Appeal ID", str(appeal_id)),
                ("Decision", decision),
                ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.id})"),
            ])
            return True

        except discord.NotFound:
            logger.warning("Cannot update appeal embed - message not found", [
                ("Message ID", str(case_message_id)),
            ])
            return False
        except discord.HTTPException as e:
            logger.warning("Failed to update appeal embed", [
                ("Appeal ID", str(appeal_id)),
                ("Error", str(e)),
            ])
            return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AppealService"]
