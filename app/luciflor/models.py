import enum
import re
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def phone_digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


class OrderStatus(str, enum.Enum):
    noua = "noua"
    in_executie = "in_executie"
    finalizata = "finalizata"
    anulata = "anulata"

    @property
    def label(self) -> str:
        return {
            "noua": "Nouă",
            "in_executie": "În execuție",
            "finalizata": "Finalizată",
            "anulata": "Anulată",
        }[self.value]


# Orders in these statuses are shown on "Lucrări în execuție".
ACTIVE_STATUSES = (OrderStatus.noua, OrderStatus.in_executie)


# Figura, parcela and loc identifiers are short alphanumeric codes (e.g. "12", "A3").
CODE_MAX_LEN = 20


def valid_code(value: str) -> bool:
    return bool(value) and len(value) <= CODE_MAX_LEN and value.isalnum()


def natural_key(value: str | None) -> list:
    """Sort "2" before "10" and "A2" before "A10"."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", value or "")]


class Figura(Base):
    """Top-level zone of the cemetery. Contains parcele."""

    __tablename__ = "figura"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(CODE_MAX_LEN), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcele: Mapped[list["Parcela"]] = relationship(
        back_populates="figura", cascade="all, delete-orphan", passive_deletes=True
    )


class Parcela(Base):
    """A parcela inside a figura; its name is unique within that figura. Orders reference a parcela + loc."""

    __tablename__ = "parcela"
    __table_args__ = (UniqueConstraint("figura_id", "name", name="uq_parcela_figura_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    figura_id: Mapped[int] = mapped_column(ForeignKey("figura.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(CODE_MAX_LEN), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    figura: Mapped[Figura] = relationship(back_populates="parcele")
    orders: Mapped[list["Order"]] = relationship(back_populates="parcela")

    @property
    def label(self) -> str:
        return f"Figura {self.figura.name} / Parcela {self.name}"


class Employee(Base):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    job_title: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Step 1 of the "Comandă nouă" workflow: client details.
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_phone: Mapped[str] = mapped_column(String(50), nullable=False)
    client_phone_digits: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    client_address: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    invoice_paid: Mapped[bool] = mapped_column(Boolean, nullable=False)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), default=OrderStatus.noua, nullable=False
    )
    # Last completed step of the new-order workflow; later steps build on this.
    workflow_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Location: figura / parcela (via parcela_id) / loc.
    parcela_id: Mapped[int | None] = mapped_column(ForeignKey("parcela.id", ondelete="SET NULL"), index=True)
    parcela: Mapped[Parcela | None] = relationship(back_populates="orders")
    loc: Mapped[str | None] = mapped_column(String(CODE_MAX_LEN))

    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def number(self) -> str:
        return f"#{self.id:05d}"

    @property
    def location(self) -> str:
        """e.g. "Figura 3 / Parcela A2 / Loc 14"; empty when no parcela is set."""
        if not self.parcela:
            return ""
        return self.parcela.label + (f" / Loc {self.loc}" if self.loc else "")
