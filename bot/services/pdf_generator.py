"""
PDF Generator service for creating customer reports
"""
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import logging

logger = logging.getLogger(__name__)

# Font registration for Cyrillic support
def register_cyrillic_fonts():
    """Register DejaVu fonts (regular + bold) and the family mapping that
    ReportLab's paraparser needs to resolve <b>...</b> inside paragraphs.
    Without registerFontFamily, ps2tt('dejavusans-bold') raises ValueError.
    """
    dejavu_paths = {
        'DejaVuSans': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'DejaVuSans-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    }

    registered = set()
    for font_name, font_path in dejavu_paths.items():
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                registered.add(font_name)
                logger.info(f"Registered font: {font_name}")
            except Exception as e:
                logger.error(f"Failed to register font {font_name}: {e}")

    if 'DejaVuSans' in registered:
        pdfmetrics.registerFontFamily(
            'DejaVuSans',
            normal='DejaVuSans',
            bold='DejaVuSans-Bold' if 'DejaVuSans-Bold' in registered else 'DejaVuSans',
            italic='DejaVuSans',
            boldItalic='DejaVuSans-Bold' if 'DejaVuSans-Bold' in registered else 'DejaVuSans',
        )

    return True

# Register fonts at module load
register_cyrillic_fonts()


class PDFGenerator:
    """Generate PDF reports for customers"""
    
    def __init__(self, temp_dir: Path):
        """
        Initialize PDF generator
        
        Args:
            temp_dir: Directory to store temporary PDF files
        """
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(exist_ok=True)
    
    def generate_customer_report(
        self,
        customer_data: Dict,
        combined_data: List[Dict] = None,
        summary: Dict = None
    ) -> Path:
        """
        Generate customer report PDF with combined orders and payments
        
        Args:
            customer_data: Customer information
            combined_data: Combined orders and payments list with cumulative debt
            summary: Summary information (optional)
            
        Returns:
            Path to generated PDF file
        """
        if combined_data is None:
            combined_data = []
        if summary is None:
            summary = {}
        
        filename = f"report_{customer_data['phone']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = self.temp_dir / filename
        
        # Create PDF (Landscape orientation)
        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=landscape(A4),
            rightMargin=0.4*inch,
            leftMargin=0.4*inch,
            topMargin=0.4*inch,
            bottomMargin=0.4*inch
        )
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1f4788'),
            spaceAfter=6,
            alignment=1,  # center
            fontName='DejaVuSans-Bold'
        )
        elements.append(Paragraph("BUYURTMALAR VA QARZYLIK HISOBOTI", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Customer Info
        customer_info_style = ParagraphStyle(
            'CustomerInfo',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=3,
            fontName='DejaVuSans'
        )
        customer_info = f"""
        <b>Mijoz nomi:</b> {customer_data['name']}<br/>
        <b>Telefon:</b> {customer_data['phone']}<br/>
        <b>Manzil:</b> {customer_data['address']}<br/>
        <b>Vaqt:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """
        elements.append(Paragraph(customer_info, customer_info_style))
        elements.append(Spacer(1, 0.15*inch))
        
        # Calculate starting and current debt
        if combined_data:
            first_transaction = combined_data[0]
            last_transaction = combined_data[-1]
            
            # Starting debt (before first transaction)
            if first_transaction['type'] == 'order':
                eski_qarzdorlik = first_transaction['cumulative_debt'] - first_transaction['remaining_debt']
            else:  # payment
                eski_qarzdorlik = first_transaction['cumulative_debt'] + first_transaction['paid_amount']
            
            # Current debt (after last transaction)
            hozirgi_qarz = last_transaction['cumulative_debt']
        else:
            eski_qarzdorlik = summary.get('total_debt', 0)
            hozirgi_qarz = summary.get('total_debt', 0)
        
        # Display starting and current debt
        debt_info_style = ParagraphStyle(
            'DebtInfo',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.black,
            spaceAfter=3,
            fontName='DejaVuSans'
        )
        elements.append(Paragraph(f"<b>Eski qarzdorlik:</b> {eski_qarzdorlik:,} so'm", debt_info_style))
        elements.append(Paragraph(f"<b>Hozirgi qarz:</b> {hozirgi_qarz:,} so'm", debt_info_style))
        elements.append(Spacer(1, 0.12*inch))
        
        # Combined Transaction History with Cumulative Debt (Web App format)
        if combined_data:
            heading_style = ParagraphStyle(
                'Heading2Custom',
                parent=styles['Heading2'],
                fontName='DejaVuSans-Bold'
            )
            elements.append(Paragraph("<b>BUYURTMALAR RO'YXATI</b>", heading_style))
            elements.append(Spacer(1, 0.1*inch))
            
            # Header row: Sana | Mahsulot | Miqdori | Narxi | Jami | Qarz
            transactions_data = [
                ['Sana', 'Mahsulot', 'Miqdori', 'Narxi', 'Jami', 'Qarz'],
            ]
            
            # Add each transaction
            for transaction in combined_data:
                if transaction['type'] == 'order':
                    product = transaction['product']
                    quantity = f"{transaction['quantity']:,}"
                    price = f"{transaction['price_per_kg']:,}"
                    total = f"{transaction['total_price']:,}"
                    debt = f"{transaction['cumulative_debt']:,}"
                    
                    transactions_data.append([
                        transaction['date'],
                        product,
                        quantity,
                        price,
                        total,
                        debt,
                    ])
                else:
                    # Payment transaction row
                    payment_type = transaction['payment_type']
                    transactions_data.append([
                        transaction['date'],
                        payment_type,
                        '-',
                        '-',
                        f"{transaction['paid_amount']:,}",
                        f"{transaction['cumulative_debt']:,}",
                    ])
            
            # Create table with landscape widths
            transactions_table = Table(transactions_data, colWidths=[1*inch, 2.5*inch, 1.2*inch, 1.2*inch, 1.5*inch, 1.5*inch])
            
            # Build table style
            table_style_commands = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eff5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('TOPPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('FONTNAME', (0, 1), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),    # Date - center
                ('ALIGN', (1, 1), (1, -1), 'LEFT'),      # Type - left
                ('ALIGN', (2, 1), (2, -1), 'CENTER'),    # Vehicle - center
                ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),    # Numeric columns - right
            ]
            
            # Color rows: light blue for orders, light green for payments
            for idx, transaction in enumerate(combined_data, start=1):
                if transaction['type'] == 'order':
                    # Light blue for orders
                    bg_color = colors.HexColor('#e3f2fd')
                else:
                    # Light green for payments
                    bg_color = colors.HexColor('#e8f5e9')
                
                table_style_commands.append(('BACKGROUND', (0, idx), (-1, idx), bg_color))
            
            transactions_table.setStyle(TableStyle(table_style_commands))
            elements.append(transactions_table)
        else:
            elements.append(Paragraph("Buyurtmalar topilmadi", styles['Normal']))
        
        # Build PDF
        doc.build(elements)

        return filepath

    def generate_supplier_report(self, report: Dict) -> Path:
        """Generate a PDF report for a supplier (firm).

        Args:
            report: Dict with keys `supplier`, `rows`, `total_purchased`,
                    `total_paid`, `debt`. Built by SupplierService.
        Returns:
            Path to the generated PDF file.
        """
        supplier = report['supplier']
        rows = report.get('rows', [])

        safe_phone = (supplier.get('phone') or 'firma').replace('+', '').replace(' ', '')
        filename = f"firma_{safe_phone}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = self.temp_dir / filename

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=landscape(A4),
            rightMargin=0.4 * inch,
            leftMargin=0.4 * inch,
            topMargin=0.4 * inch,
            bottomMargin=0.4 * inch,
        )

        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle(
            'SupplierTitle', parent=styles['Heading1'], fontSize=16,
            textColor=colors.HexColor('#1f4788'), spaceAfter=6,
            alignment=1, fontName='DejaVuSans-Bold',
        )
        elements.append(Paragraph("FIRMA HISOBOTI", title_style))
        elements.append(Spacer(1, 0.2 * inch))

        info_style = ParagraphStyle(
            'SupplierInfo', parent=styles['Normal'], fontSize=10,
            textColor=colors.black, spaceAfter=3, fontName='DejaVuSans',
        )
        info = (
            f"<b>Firma nomi:</b> {supplier['name']}<br/>"
            f"<b>Telefon:</b> {supplier.get('phone') or '—'}<br/>"
            f"<b>Manzil:</b> {supplier.get('address') or '—'}<br/>"
            f"<b>Vaqt:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        elements.append(Paragraph(info, info_style))
        elements.append(Spacer(1, 0.15 * inch))

        debt_style = ParagraphStyle(
            'SupplierDebt', parent=styles['Normal'], fontSize=11,
            textColor=colors.black, spaceAfter=3, fontName='DejaVuSans',
        )
        elements.append(Paragraph(
            f"<b>Eski qarz:</b> {supplier.get('initial_debt', 0):,} so'm", debt_style))
        elements.append(Paragraph(
            f"<b>Jami xarid:</b> {report.get('total_purchased', 0):,} so'm", debt_style))
        elements.append(Paragraph(
            f"<b>Jami to'lov:</b> {report.get('total_paid', 0):,} so'm", debt_style))
        elements.append(Paragraph(
            f"<b>Hozirgi qarz:</b> {report.get('debt', 0):,} so'm", debt_style))
        elements.append(Spacer(1, 0.12 * inch))

        if rows:
            heading_style = ParagraphStyle(
                'SupplierHeading', parent=styles['Heading2'], fontName='DejaVuSans-Bold',
            )
            elements.append(Paragraph("<b>HARAKATLAR RO'YXATI</b>", heading_style))
            elements.append(Spacer(1, 0.1 * inch))

            data = [['Sana', 'Tur', 'Tafsilot', 'Miqdor', 'Birlik narxi', 'Summa', 'Qarz']]
            for r in rows:
                data.append([
                    r['date'],
                    ('Xarid' if r['type'] == 'purchase' else 'To\'lov') + f" ({r['kind']})",
                    r['description'],
                    f"{r['quantity']:,}" if r['quantity'] else '-',
                    f"{r['price_per_unit']:,}" if r['price_per_unit'] else '-',
                    f"{r['amount']:,}",
                    f"{r['cumulative_debt']:,}",
                ])

            table = Table(data, colWidths=[
                0.9 * inch, 1.4 * inch, 2.4 * inch, 0.9 * inch,
                1.1 * inch, 1.3 * inch, 1.3 * inch,
            ])

            style_cmds = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eff5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('TOPPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('FONTNAME', (0, 1), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                ('ALIGN', (1, 1), (2, -1), 'LEFT'),
                ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ]
            for idx, r in enumerate(rows, start=1):
                bg = colors.HexColor('#fde4e4') if r['type'] == 'purchase' else colors.HexColor('#e8f5e9')
                style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), bg))

            table.setStyle(TableStyle(style_cmds))
            elements.append(table)
        else:
            elements.append(Paragraph("Harakatlar topilmadi", styles['Normal']))

        doc.build(elements)
        return filepath
