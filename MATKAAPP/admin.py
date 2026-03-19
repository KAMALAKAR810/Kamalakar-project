from django.contrib import admin
from .models import MatkaNumber
from .models import *

# Register your models here.
admin.site.register(MatkaNumber)


from django.contrib import admin
from .models import Bet

@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = ('user', 'market_name', 'game_type', 'number', 'amount', 'status', 'created_at')
    list_filter = ('status', 'game_type', 'market_name')
    
    
admin.site.register(Wallet)
admin.site.register(Transaction)