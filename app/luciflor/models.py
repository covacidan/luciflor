import enum
import re
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
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


class Tarla(Base):
    """A plot/zone inside the cemetery, used to group orders."""

    __tablename__ = "tarla"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(back_populates="tarla")


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

    tarla_id: Mapped[int | None] = mapped_column(ForeignKey("tarla.id", ondelete="SET NULL"))
    tarla: Mapped[Tarla | None] = relationship(back_populates="orders")

    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def number(self) -> str:
        return f"#{self.id:05d}"
