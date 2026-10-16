from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from uuid import UUID
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from packages.database.session import get_db
from packages.database.models import ClientRoom, Message, User, AuditEvent, Defect, TestCase, Client, MessageMention, MessageAttachment
from packages.shared_dtos.messaging_dtos import (
    MessageCreate,
    MessageRead,
    MentionCreate,
    MentionRead,
    AttachmentCreate,
    AttachmentRead,
    ConversationCreate,
    ConversationRead,
    WorkitemConvertRequest,
    ClientRoomCreate,
    ClientRoomRead,
    ClientRoomStatusUpdate,
    DefectRead,
    DefectStatusUpdate
)
from apps.core_gateway.security import (
    get_current_tenant,
    get_current_active_user,
    RoleChecker
)


router = APIRouter(prefix="/api", tags=["Operational Messaging & Client Rooms"])

class MessageEditRequest(BaseModel):
    content: str

# Helper to create audit logs
def log_audit_event(db: Session, tenant_id: UUID, user_id: UUID, action: str, entity: str, entity_id: UUID, diff: str = None):
    audit = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action_name=action,
        entity_name=entity,
        entity_id=entity_id,
        diff_data=diff,
        created_at=datetime.utcnow()
    )
    db.add(audit)

# --- CLIENT ROOM MESSAGE STREAM ENDPOINTS ---

@router.get("/client-rooms/{client_room_id}/messages", response_model=List[MessageRead])
def get_room_messages(
    client_room_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    room = db.query(ClientRoom).filter(ClientRoom.id == client_room_id, ClientRoom.tenant_id == tenant_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Client room not found")
        
    query = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(Message.client_room_id == client_room_id)
    
    # Security Rule: Separate client-visible and internal streams.
    # Client Representative role is forbidden from seeing internal messages.
    if current_user.role == "client_rep":
        query = query.filter(Message.visibility == "external")
        
    messages = query.order_by(Message.created_at.asc()).all()
    for m in messages:
        if m.deleted_at is not None:
            m.content = "[deleted]"
    return messages

@router.post("/client-rooms/{client_room_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def send_room_message(
    client_room_id: UUID,
    message_in: MessageCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    room = db.query(ClientRoom).filter(ClientRoom.id == client_room_id, ClientRoom.tenant_id == tenant_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Client room not found")
        
    # Security Rule: Client Representative can only send external messages.
    visibility = message_in.visibility
    if current_user.role == "client_rep":
        if visibility != "external":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Clients can only send external messages"
            )
            
    msg = Message(
        id=uuid.uuid4(),
        client_room_id=client_room_id,
        sender_id=current_user.id,
        content_type=message_in.content_type,
        content=message_in.content,
        visibility=visibility,
        parent_message_id=message_in.parent_message_id,
        created_at=datetime.utcnow()
    )
    db.add(msg)

    # Mentions
    for mentioned_id in (message_in.mentioned_user_ids or []):
        db.add(MessageMention(id=uuid.uuid4(), message_id=msg.id, mentioned_user_id=mentioned_id, created_at=datetime.utcnow()))

    # Attachments
    for att in (message_in.attachments or []):
        db.add(MessageAttachment(
            id=uuid.uuid4(), message_id=msg.id,
            file_url=att.file_url, file_name=att.file_name,
            file_type=att.file_type, file_size=att.file_size,
            created_at=datetime.utcnow()
        ))
    
    # Audit trail
    log_audit_event(
        db, tenant_id, current_user.id, "send_message", "Message", msg.id,
        diff=f"content_length: {len(msg.content)}, visibility: {msg.visibility}"
    )
    
    try:
        db.commit()
        # Eager load sender for response model serialization
        msg_loaded = db.query(Message).options(
            joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
        ).filter(Message.id == msg.id).first()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
    return msg_loaded

@router.post("/client-rooms/{client_room_id}/read")
def mark_room_read(
    client_room_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    room = db.query(ClientRoom).filter(ClientRoom.id == client_room_id, ClientRoom.tenant_id == tenant_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Client room not found")

    query = db.query(Message).filter(
        Message.client_room_id == client_room_id,
        Message.sender_id != current_user.id,
        Message.read_at.is_(None),
        Message.content_type != "system"
    )
    if current_user.role == "client_rep":
        query = query.filter(Message.visibility == "external")

    unread = query.all()
    for msg in unread:
        msg.read_at = datetime.utcnow()
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    return {"marked_read": len(unread)}

# --- PERSONAL DIRECT CHAT (DM) ENDPOINTS ---

@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def start_conversation(
    conv_in: ConversationCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    # DMs are internal only - verify all participants belong to the same tenant and are internal
    participants = list(set(conv_in.participant_ids + [current_user.id]))
    
    for p_id in participants:
        p_user = db.query(User).filter(User.id == p_id, User.tenant_id == tenant_id).first()
        if not p_user:
            raise HTTPException(
                status_code=400,
                detail=f"Participant {p_id} is invalid or belongs to a different tenant"
            )
        if p_user.role == "client_rep":
            raise HTTPException(
                status_code=400,
                detail="Clients cannot participate in internal DMs"
            )
            
    # Generate deterministic conversation ID
    sorted_ids = sorted(str(p_id) for p_id in participants)
    conv_id = uuid.uuid5(uuid.NAMESPACE_DNS, "-".join(sorted_ids))
    
    # Check if conversation already exists (verified by checking system participant message)
    existing_sys_msg = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.content_type == "system",
        Message.content.like("participants:%")
    ).first()
    
    if not existing_sys_msg:
        # Create initial system message to track participants securely
        sys_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv_id,
            sender_id=None,
            content_type="system",
            content=f"participants:{','.join(str(p_id) for p_id in participants)}",
            visibility="internal",
            created_at=datetime.utcnow()
        )
        db.add(sys_msg)
        db.commit()
        
    return {"id": conv_id, "created_at": datetime.utcnow()}

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageRead])
def get_conversation_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    # Find system participant message to verify membership
    sys_msg = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.content_type == "system",
        Message.content.like("participants:%")
    ).first()
    
    if not sys_msg:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    participants_str = sys_msg.content.replace("participants:", "")
    participant_ids = [UUID(p_id.strip()) for p_id in participants_str.split(",")]
    
    # Security Rule: Direct-chat content is not readable by anyone outside the conversation.
    if current_user.id not in participant_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation"
        )
        
    messages = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(
        Message.conversation_id == conversation_id,
        Message.content_type != "system"
    ).order_by(Message.created_at.asc()).all()

    for m in messages:
        if m.deleted_at is not None:
            m.content = "[deleted]"
    return messages

@router.post("/conversations/{conversation_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def send_conversation_message(
    conversation_id: UUID,
    message_in: MessageCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    # Find system participant message to verify membership
    sys_msg = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.content_type == "system",
        Message.content.like("participants:%")
    ).first()
    
    if not sys_msg:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    participants_str = sys_msg.content.replace("participants:", "")
    participant_ids = [UUID(p_id.strip()) for p_id in participants_str.split(",")]
    
    if current_user.id not in participant_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation"
        )
        
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content_type=message_in.content_type,
        content=message_in.content,
        visibility="internal", # DMs are always internal
        parent_message_id=message_in.parent_message_id,
        created_at=datetime.utcnow()
    )
    db.add(msg)

    # Mentions
    for mentioned_id in (message_in.mentioned_user_ids or []):
        db.add(MessageMention(id=uuid.uuid4(), message_id=msg.id, mentioned_user_id=mentioned_id, created_at=datetime.utcnow()))

    # Attachments
    for att in (message_in.attachments or []):
        db.add(MessageAttachment(
            id=uuid.uuid4(), message_id=msg.id,
            file_url=att.file_url, file_name=att.file_name,
            file_type=att.file_type, file_size=att.file_size,
            created_at=datetime.utcnow()
        ))
    
    try:
        db.commit()
        # Eager load sender for response model serialization
        msg_loaded = db.query(Message).options(
            joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
        ).filter(Message.id == msg.id).first()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
    return msg_loaded

@router.post("/conversations/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    unread = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sender_id != current_user.id,
        Message.read_at.is_(None),
        Message.content_type != "system"
    ).all()
    for msg in unread:
        msg.read_at = datetime.utcnow()
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    return {"marked_read": len(unread)}

# --- WORKITEM CONVERSION ENDPOINT ---

@router.post("/messages/{message_id}/convert", status_code=status.HTTP_201_CREATED)
def convert_message_to_workitem(
    message_id: UUID,
    req: WorkitemConvertRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
        
    target_id = uuid.uuid4()
    
    if req.target_type in ["defect", "task"]:
        # Create Defect
        owner_id = req.owner_id or current_user.id
        defect = Defect(
            id=target_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            severity=req.severity,
            steps_to_reproduce=f"Message context:\n{message.content}",
            expected="Resolved operational flow",
            actual="Incorrect operational state",
            status="open",
            created_at=datetime.utcnow()
        )
        db.add(defect)
        
        # System notification message in the room
        sys_note = Message(
            id=uuid.uuid4(),
            client_room_id=message.client_room_id,
            conversation_id=message.conversation_id,
            sender_id=None,
            content_type="system",
            content=f"Workflow action: Converted message into {req.target_type} '{target_id}' (severity: {req.severity})",
            visibility=message.visibility,
            created_at=datetime.utcnow()
        )
        db.add(sys_note)
        
    elif req.target_type == "test_case":
        # Create TestCase
        test_case = TestCase(
            id=target_id,
            tenant_id=tenant_id,
            scenario=f"Scenario converted from conversation message:\n{message.content}",
            expected_result="Verified successfully",
            test_group="regression",
            created_at=datetime.utcnow()
        )
        db.add(test_case)
        
        sys_note = Message(
            id=uuid.uuid4(),
            client_room_id=message.client_room_id,
            conversation_id=message.conversation_id,
            sender_id=None,
            content_type="system",
            content=f"Workflow action: Converted message into test case '{target_id}'",
            visibility=message.visibility,
            created_at=datetime.utcnow()
        )
        db.add(sys_note)
        
    else:
        raise HTTPException(status_code=400, detail="Invalid target type (must be 'defect', 'task', or 'test_case')")
        
    # Log audit event
    log_audit_event(
        db, tenant_id, current_user.id, "convert_message", "Message", message.id,
        diff=f"target_type: {req.target_type}, target_id: {target_id}"
    )
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database transaction failed: {str(e)}")
        
    return {
        "status": "converted",
        "target_type": req.target_type,
        "target_id": str(target_id)
    }


# --- NEW TICKET & TASK LIFE CYCLE ENDPOINTS ---

@router.post("/client-rooms", response_model=ClientRoomRead, status_code=status.HTTP_201_CREATED)
def create_client_room(
    req: ClientRoomCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    # Check if client exists and belongs to the tenant
    client = db.query(Client).filter(Client.id == req.client_id, Client.tenant_id == tenant_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    room_id = uuid.uuid4()
    room = ClientRoom(
        id=room_id,
        client_id=req.client_id,
        tenant_id=tenant_id,
        status="active",
        created_at=datetime.utcnow()
    )
    db.add(room)
    
    # Audit log
    log_audit_event(db, tenant_id, current_user.id, "create", "client_rooms", room_id)
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create client room: {str(e)}")
        
    return room


@router.get("/client-rooms", response_model=List[ClientRoomRead])
def list_client_rooms(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    rooms = db.query(ClientRoom).filter(ClientRoom.tenant_id == tenant_id).all()
    return rooms


@router.patch("/client-rooms/{client_room_id}/status", response_model=ClientRoomRead)
def update_client_room_status(
    client_room_id: UUID,
    req: ClientRoomStatusUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    room = db.query(ClientRoom).filter(
        ClientRoom.id == client_room_id,
        ClientRoom.tenant_id == tenant_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Client room not found")
        
    old_status = room.status
    room.status = req.status
    
    # Audit log
    log_audit_event(
        db, tenant_id, current_user.id, "update_status", "client_rooms", client_room_id,
        diff=f"status: {old_status} -> {req.status}"
    )
    
    # Post a system notification message inside the room
    sys_note = Message(
        id=uuid.uuid4(),
        client_room_id=room.id,
        sender_id=None,
        content_type="system",
        content=f"Room status updated to '{req.status}' by {current_user.full_name}",
        visibility="external",
        created_at=datetime.utcnow()
    )
    db.add(sys_note)
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update room status: {str(e)}")
        
    return room


@router.get("/defects", response_model=List[DefectRead])
def list_defects(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    defects = db.query(Defect).filter(Defect.tenant_id == tenant_id).all()
    return defects


@router.patch("/defects/{defect_id}/status", response_model=DefectRead)
def update_defect_status(
    defect_id: UUID,
    req: DefectStatusUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    defect = db.query(Defect).filter(
        Defect.id == defect_id,
        Defect.tenant_id == tenant_id
    ).first()
    if not defect:
        raise HTTPException(status_code=404, detail="Defect/Task not found")
        
    old_status = defect.status
    defect.status = req.status
    
    # Audit log
    log_audit_event(
        db, tenant_id, current_user.id, "update_status", "defects", defect_id,
        diff=f"status: {old_status} -> {req.status}"
    )
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update defect/task status: {str(e)}")
        
    return defect


@router.get("/messages/{message_id}/thread", response_model=List[MessageRead])
def get_message_thread(
    message_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    parent = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(Message.id == message_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Message not found")

    replies = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(Message.parent_message_id == message_id).order_by(Message.created_at.asc()).all()

    if parent.deleted_at is not None:
        parent.content = "[deleted]"

    for r in replies:
        if r.deleted_at is not None:
            r.content = "[deleted]"

    return [parent] + replies

@router.patch("/messages/{message_id}", response_model=MessageRead)
def edit_message(
    message_id: UUID,
    req: MessageEditRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    msg = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.conversation_id:
        sys_msg = db.query(Message).filter(
            Message.conversation_id == msg.conversation_id,
            Message.content_type == "system",
            Message.content.like("participants:%")
        ).first()
        if not sys_msg:
            raise HTTPException(status_code=404, detail="Conversation not found")
        participants_str = sys_msg.content.replace("participants:", "")
        participant_ids = [UUID(p_id.strip()) for p_id in participants_str.split(",")]
        if current_user.id not in participant_ids:
            raise HTTPException(status_code=403, detail="You are not a participant in this conversation")

    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can edit this message")

    if msg.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")

    old_content = msg.content
    msg.content = req.content
    msg.edited_at = datetime.utcnow()

    log_audit_event(
        db, tenant_id, current_user.id, "edit_message", "Message", msg.id,
        diff=f"old_content: {old_content}, new_content: {req.content}"
    )

    try:
        db.commit()
        db.refresh(msg)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return msg

@router.delete("/messages/{message_id}", response_model=MessageRead)
def delete_message(
    message_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    msg = db.query(Message).options(
        joinedload(Message.sender), joinedload(Message.mentions), joinedload(Message.attachments)
    ).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.conversation_id:
        sys_msg = db.query(Message).filter(
            Message.conversation_id == msg.conversation_id,
            Message.content_type == "system",
            Message.content.like("participants:%")
        ).first()
        if not sys_msg:
            raise HTTPException(status_code=404, detail="Conversation not found")
        participants_str = sys_msg.content.replace("participants:", "")
        participant_ids = [UUID(p_id.strip()) for p_id in participants_str.split(",")]
        if current_user.id not in participant_ids:
            raise HTTPException(status_code=403, detail="You are not a participant in this conversation")

    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can delete this message")

    msg.deleted_at = datetime.utcnow()

    log_audit_event(
        db, tenant_id, current_user.id, "delete_message", "Message", msg.id,
        diff=f"deleted_content: {msg.content}"
    )

    try:
        db.commit()
        db.refresh(msg)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    msg.content = "[deleted]"
    return msg

