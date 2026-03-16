from django.db import models

class MatkaNumber(models.Model):
    m_name = models.CharField(max_length=100, default="Lucky Drop", blank=True)
    m_time_1 = models.TimeField(null=True, blank=True, verbose_name="Opening Time")
    m_time_2 = models.TimeField(null=True, blank=True, verbose_name="Closing Time")
    m_number_1 = models.CharField(max_length=100, null=True, blank=True)
    m_number_2 = models.CharField(max_length=100, null=True, blank=True)
    m_number_3 = models.CharField(max_length=100, null=True, blank=True)
    m_number_4 = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.m_name} ({self.m_number_2}{self.m_number_3})"