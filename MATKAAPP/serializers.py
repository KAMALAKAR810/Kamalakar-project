from rest_framework import serializers
from .models import Wallet, Transaction

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        # Using __all__ is safer if you want everything, or keep your list
        fields = ['id', 'amount', 'txn_type', 'description', 'created_at']

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        # Removed 'updated_at' to prevent "Field name is not valid" error
        fields = ['balance']