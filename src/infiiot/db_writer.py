import os
import json
from datetime import datetime
from typing import Optional, List, Dict
from urllib.parse import quote_plus
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, select, func
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database Connection
DB_USER = os.getenv("AI_DB_USER", "akshay")
DB_PASS = os.getenv("AI_DB_PASSWORD", "pass@123")
DB_HOST = os.getenv("AI_DB_HOST", "localhost")
DB_PORT = os.getenv("AI_DB_PORT", "5432")
DB_NAME = os.getenv("AI_DB_NAME", "postgres")

# --- DATABASE CONFIGURATION ---
# We use quote_plus to handle special characters (like '@' or '#') in the DB password
# This prevents SQLAlchemy connection errors.
encoded_password = quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- DATABASE MODELS (SQLAlchemy) ---
# These classes map directly to your PostgreSQL tables.

# --- Models Matching Django Schema ---

class User(Base):
    __tablename__ = "auth_user"
    id = Column(Integer, primary_key=True)
    username = Column(String(150))

class DashboardName(Base):
    __tablename__ = "dashboard_dashboardname"
    id = Column(Integer, primary_key=True)
    user_id_id = Column(Integer, ForeignKey("auth_user.id"))
    dashboard_id = Column(Integer)
    dashboard_name = Column(String(20))
    default_dashboard = Column(Boolean, default=False)
    interval = Column(String(2))
    realtime = Column(String(3))

class VariableDir(Base):
    __tablename__ = "devices_variabledir"
    id = Column(Integer, primary_key=True)
    variable_id = Column(Integer)
    variable_name = Column(String(50))
    project_id_id = Column(Integer, ForeignKey("devices_projectdir.id"))
    unit = Column(String(8), default="unit")
    linked_with_synthetic = Column(Boolean, default=False)
    have_event = Column(Boolean, default=False)
    is_map = Column(Boolean, default=False)
    is_synthetic = Column(Boolean, default=False)

class ProjectDir(Base):
    __tablename__ = "devices_projectdir"
    id = Column(Integer, primary_key=True)
    user_id_id = Column(Integer, ForeignKey("auth_user.id"))
    project_name = Column(String(50))
    project_id = Column(String(100))
    token_id_id = Column(Integer)
    mac_id = Column(String(100))
    latitude = Column(String(20), default="0")
    longitude = Column(String(20), default="0")
    last_updated = Column(DateTime, default=datetime.now)

class Widget(Base):
    __tablename__ = "dashboard_widgets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id_id = Column(Integer, ForeignKey("auth_user.id"))
    widget_id = Column(Integer)
    dashboard_id_id = Column(Integer, ForeignKey("dashboard_dashboardname.id"))
    variable_id_id = Column(Integer, ForeignKey("devices_variabledir.id"))
    widgetType = Column(String(20))
    widgetSubType = Column(String(20))
    position = Column(Integer)
    min = Column(String(20))
    max = Column(String(20))
    unit = Column(String(15))
    title = Column(String(25))
    color = Column(String(20))
    xlabel = Column(String(20))
    ylabel = Column(String(20))
    axis = Column(String(10))
    smooth = Column(Boolean, default=False)

# --- Write Logic ---

def create_dashboard_direct(user_id: int, dashboard_name: str) -> Dict[str, object]:
    """Create a new dashboard record directly."""
    session = SessionLocal()
    try:
        # Check if already exists
        exists = session.query(DashboardName).filter(
            DashboardName.user_id_id == user_id, 
            DashboardName.dashboard_name == dashboard_name
        ).first()
        if exists:
            return {"ok": False, "message": f"Dashboard '{dashboard_name}' already exists.", "dashboard_id": exists.id}

        # Get next dashboard_id (numerical)
        max_id = session.query(func.max(DashboardName.dashboard_id)).filter(DashboardName.user_id_id == user_id).scalar() or 0
        
        new_db = DashboardName(
            user_id_id=user_id,
            dashboard_id=max_id + 1,
            dashboard_name=dashboard_name,
            default_dashboard=False
        )
        session.add(new_db)
        session.commit()
        return {"ok": True, "message": "Dashboard created.", "dashboard_id": new_db.id}
    except Exception as e:
        session.rollback()
        return {"ok": False, "message": str(e)}
    finally:
        session.close()

def create_variable_direct(user_id: int, project_name: str, variable_name: Optional[str], unit: str = "unit") -> Dict[str, object]:
    """Create a project or a variable under a project."""
    session = SessionLocal()
    try:
        # STEP 1: Find or Create the Project
        # A variable must belong to a project. We check if it exists first.
        project = session.query(ProjectDir).filter(
            ProjectDir.user_id_id == user_id,
            ProjectDir.project_name == project_name
        ).first()

        if not project:
            # If project doesn't exist, create it automatically
            project = ProjectDir(
                user_id_id=user_id,
                project_name=project_name,
                project_id=f"{project_name}_{user_id}"
            )
            session.add(project)
            session.flush() # Flush to generate the 'id' for use below

        # If user only wanted to create a project (no variable name provided), we stop here.
        if not variable_name:
            session.commit()
            return {"ok": True, "message": f"Project '{project_name}' created/verified."}

        # STEP 2: Ensure the Variable exists
        exists = session.query(VariableDir).filter(
            VariableDir.project_id_id == project.id,
            VariableDir.variable_name == variable_name
        ).first()
        
        if exists:
            return {"ok": True, "message": f"Variable '{variable_name}' already exists."}

        # Get next variable_id (numeric) for this project
        max_var_id = session.query(func.max(VariableDir.variable_id)).filter(VariableDir.project_id_id == project.id).scalar() or 0

        new_var = VariableDir(
            project_id_id=project.id,
            variable_id=max_var_id + 1,
            variable_name=variable_name,
            unit=unit,
            linked_with_synthetic=False,
            have_event=False,
            is_map=False,
            is_synthetic=False
        )
        session.add(new_var)
        session.commit()
        return {"ok": True, "message": f"Variable '{variable_name}' created under '{project_name}'."}
    except Exception as e:
        session.rollback()
        return {"ok": False, "message": str(e)}
    finally:
        session.close()

def create_widget_direct(
    user_id: int,
    dashboard_db_id: int,
    variable_db_id: int,
    widget_type: str,
    widget_subtype: str,
    title: str,
    ymin: str = "0",
    ymax: str = "100",
    xlabel: str = "Time",
    ylabel: str = "Value",
    unit: str = "",
    color: str = "#4488ff",
) -> Dict[str, object]:
    """
    Directly insert a widget into the dashboard_widgets table.
    Replicates Django logic for widget_id and position.
    """
    session = SessionLocal()
    try:
        # 1. Calculate next global widget_id (matching Django dashboard/views.py:364)
        max_widget_id = session.query(func.max(Widget.widget_id)).scalar() or 0
        next_widget_id = max_widget_id + 1

        # 2. Calculate next position for this specific user (matching Django dashboard/views.py:365)
        max_position = session.query(func.max(Widget.position)).filter(Widget.user_id_id == user_id).scalar() or 0
        next_position = max_position + 1

        # 3. Create Widget instance
        new_widget = Widget(
            user_id_id=user_id,
            widget_id=next_widget_id,
            dashboard_id_id=dashboard_db_id,
            variable_id_id=variable_db_id,
            widgetType=widget_type,
            widgetSubType=widget_subtype,
            position=next_position,
            title=title,
            min=ymin,
            max=ymax,
            xlabel=xlabel,
            ylabel=ylabel,
            unit=unit,
            color=color,
            smooth=False
        )

        session.add(new_widget)
        session.commit()
        
        return {
            "ok": True,
            "message": "Widget created successfully via direct DB write.",
            "widget_id": next_widget_id,
            "position": next_position
        }
    except Exception as e:
        session.rollback()
        return {"ok": False, "message": f"DB Write Error: {str(e)}"}
    finally:
        session.close()
