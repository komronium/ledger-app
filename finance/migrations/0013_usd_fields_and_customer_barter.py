from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0012_alter_purchase_price_per_unit_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymenthistory',
            name='usd_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True, verbose_name='Dollar miqdori'),
        ),
        migrations.AddField(
            model_name='paymenthistory',
            name='exchange_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Kurs (so'm)"),
        ),
        migrations.AddField(
            model_name='paymenthistory',
            name='barter_product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customer_barters', to='finance.product', verbose_name='Barter mahsuloti'),
        ),
        migrations.AddField(
            model_name='paymenthistory',
            name='barter_quantity',
            field=models.IntegerField(default=0, verbose_name='Barter miqdori'),
        ),
        migrations.AlterField(
            model_name='paymenthistory',
            name='payment_type',
            field=models.CharField(blank=True, choices=[('bank', "Pul ko'chirish"), ('cash', 'Naqd'), ('click', 'Click'), ('barter', 'Barter (Mahsulot bilan)')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='purchase',
            name='usd_price_per_unit',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Dollar birlik narxi'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='exchange_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Kurs (so'm)"),
        ),
        migrations.AddField(
            model_name='supplierpayment',
            name='usd_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True, verbose_name='Dollar miqdori'),
        ),
        migrations.AddField(
            model_name='supplierpayment',
            name='exchange_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Kurs (so'm)"),
        ),
    ]
